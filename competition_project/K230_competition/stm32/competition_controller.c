#include "competition_controller.h"
#include <stdio.h>
#include <string.h>

int competition_step(const VisionTask *t,unsigned index,CompetitionStep *s) {
    static const char *phases[]={"RAW1","PROCESS_PUT1","PROCESS_GET1","STORE1",
                                "RAW2","PROCESS_PUT2","PROCESS_GET2","STACK2"};
    unsigned phase=index/3, item=index%3, batch=phase/4;
    if (!t || !t->valid || index>=24 || !s) return 0;
    memset(s,0,sizeof(*s)); s->index=index; s->phase=phases[phase];
    s->color=t->color[batch][item];
    switch (phase%4) {
    case 0: s->mode="COLOR"; s->profile="RAW"; s->pick=1; break;
    case 1: s->mode="RING"; s->profile="PROCESS"; s->slot=t->process_slot[batch][item]; break;
    case 2: s->mode="COLOR"; s->profile="PROCESS"; s->slot=t->process_slot[batch][item]; s->pick=1; break;
    default: s->mode=batch?"COLOR":"RING"; s->profile=batch?"STACK":"STORE";
             s->slot=t->store_slot[batch][item]; s->stack=(uint8_t)(batch!=0); break;
    }
    return 1;
}
int competition_init(CompetitionController *c,const CompetitionIO *io) {
    if (!c || !io || !io->send || !io->prepare_start || !io->prepare_poll ||
        !io->action_start || !io->action_poll || !io->home_start || !io->home_poll || !io->stop) return 0;
    memset(c,0,sizeof(*c)); c->io=*io; vision_init(&c->vision);
    c->request_timeout_ms=1500; c->motion_timeout_ms=30000; c->locate_timeout_ms=30000;
    c->max_result_latency_ms=600; c->require_mm=1; c->state=CC_WAIT_START; return 1;
}
void competition_feed(CompetitionController *c,const uint8_t *bytes,size_t length) {
    vision_feed(&c->vision,bytes,length);
}
void competition_abort(CompetitionController *c,const char *reason) {
    char packet[108]; size_t n;
    if (c->state==CC_FAULT) return;
    c->io.stop(); c->vision.pending=0;
    n=vision_request(&c->vision,++c->seq,"STOP",0,c->request_timeout_ms,packet,sizeof(packet));
    if (n) c->io.send((const uint8_t*)packet,n);
    snprintf(c->error,sizeof(c->error),"%s",reason); c->state=CC_FAULT;
}
static void send_request(CompetitionController *c,unsigned state,uint32_t now) {
    char packet[108]; size_t n;
    if (state==CC_RESET) n=vision_request(&c->vision,++c->seq,"RESET",now,c->request_timeout_ms,packet,sizeof(packet));
    else if (state==CC_ACK) n=vision_ack_task(&c->vision,++c->seq,now,c->request_timeout_ms,packet,sizeof(packet));
    else if (state==CC_STEP) n=vision_confirm_step(&c->vision,++c->seq,c->step,now,c->request_timeout_ms,packet,sizeof(packet));
    else if (state==CC_FINAL_ACK) n=vision_home_done(&c->vision,++c->seq,now,c->request_timeout_ms,packet,sizeof(packet));
    else n=vision_request_profile(&c->vision,++c->seq,c->current.mode,c->current.profile,now,
                                  c->request_timeout_ms,packet,sizeof(packet));
    if (!n) { competition_abort(c,"REQUEST_FAILED"); return; }
    c->last_request_ms=now; c->state=state; c->io.send((const uint8_t*)packet,n);
}
int competition_start(CompetitionController *c,uint32_t now) {
    if (!c || c->state!=CC_WAIT_START) return 0;
    c->io.stop(); c->vision.pending=0;
    memset(&c->vision.task,0,sizeof(c->vision.task));
    c->retries=0; send_request(c,CC_RESET,now);
    return c->state==CC_RESET;
}
static void prepare(CompetitionController *c,uint32_t now) {
    if (!competition_step(&c->vision.task,c->step,&c->current)) { competition_abort(c,"PLAN_FAILED"); return; }
    c->io.prepare_start(&c->current); c->stage_ms=now; c->state=CC_PREPARE;
}
void competition_tick(CompetitionController *c,uint32_t now) {
    VisionClient *v=&c->vision; int status; unsigned i;
    if (c->state==CC_FAULT || c->state==CC_FINISHED) return;
    vision_tick(v,now);
    if (v->failed && !strcmp(v->error,"TASK_CHANGED")) { competition_abort(c,"TASK_CHANGED"); return; }
    switch(c->state) {
    case CC_WAIT_START: break;
    case CC_WAIT_TASK:
        if (v->task.valid) { c->retries=0; send_request(c,CC_ACK,now); }
        break;
    case CC_ACK:
    case CC_STEP:
    case CC_FINAL_ACK:
    case CC_RESET:
        if (v->pending) break;
        if (v->timed_out) {
            if (++c->retries>3) competition_abort(c,"LINK_TIMEOUT");
            else send_request(c,c->state,now); /* STEP retries are idempotent. */
            break;
        }
        if (!v->complete || v->failed || !v->ack ||
            (c->state==CC_STEP && v->ack_step!=(int)c->step)) {
            competition_abort(c,"ACK_FAILED"); break;
        }
        c->retries=0;
        if (c->state==CC_RESET) { c->state=CC_WAIT_TASK; break; }
        if (c->state==CC_FINAL_ACK) { c->state=CC_FINISHED; break; }
        if (c->state==CC_ACK) { prepare(c,now); break; }
        if (c->current.pick) ++c->grabs; else ++c->places;
        ++c->step;
        if (c->step==24) { c->io.home_start(); c->state=CC_HOME; c->stage_ms=now; }
        else prepare(c,now);
        break;
    case CC_PREPARE:
        status=c->io.prepare_poll();
        if (status<0) competition_abort(c,"PREPARE_FAILED");
        else if ((uint32_t)(now-c->stage_ms)>c->motion_timeout_ms) competition_abort(c,"PREPARE_TIMEOUT");
        else if (status==1) { c->stage_ms=now; send_request(c,CC_LOCATE,now); }
        break;
    case CC_LOCATE:
        if ((uint32_t)(now-c->stage_ms)>c->locate_timeout_ms) { competition_abort(c,"LOCATE_TIMEOUT"); break; }
        if (v->pending) break;
        if (v->complete && !v->failed && (uint32_t)(now-v->requested_ms)<=c->max_result_latency_ms) {
            for (i=0;i<v->count;++i) {
                VisionRecord *r=&v->records[i];
                int expected=!strcmp(c->current.mode,"COLOR")?c->current.color:c->current.slot;
                if (r->id==expected && r->valid && r->stable && (!c->require_mm || r->calibrated)) {
                    c->io.action_start(&c->current,r); c->state=CC_ACTION; c->stage_ms=now; return;
                }
            }
        }
        if (v->failed && !v->timed_out) { competition_abort(c,v->error); break; }
        if (v->timed_out && ++c->retries>3) { competition_abort(c,"LINK_TIMEOUT"); break; }
        if (!v->timed_out) c->retries=0;
        if ((uint32_t)(now-c->last_request_ms)>=100) send_request(c,CC_LOCATE,now);
        break;
    case CC_ACTION:
        status=c->io.action_poll();
        if (status<0) competition_abort(c,"ACTION_FAILED");
        else if ((uint32_t)(now-c->stage_ms)>c->motion_timeout_ms) competition_abort(c,"ACTION_TIMEOUT");
        else if (status==1) { c->retries=0; send_request(c,CC_STEP,now); }
        break;
    case CC_HOME:
        status=c->io.home_poll();
        if (status<0) competition_abort(c,"HOME_FAILED");
        else if ((uint32_t)(now-c->stage_ms)>c->motion_timeout_ms) competition_abort(c,"HOME_TIMEOUT");
        else if (status==1) { c->retries=0; send_request(c,CC_FINAL_ACK,now); }
        break;
    default: competition_abort(c,"BAD_STATE"); break;
    }
}
