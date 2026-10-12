#include "vision_client.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <errno.h>
#include <math.h>

uint16_t vision_crc16(const uint8_t *data, size_t length) {
    uint16_t crc = 0xFFFF;
    size_t i; unsigned bit;
    for (i = 0; i < length; ++i) {
        crc ^= (uint16_t)data[i] << 8;
        for (bit = 0; bit < 8; ++bit)
            crc = (uint16_t)((crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1);
    }
    return crc;
}

void vision_init(VisionClient *c) { memset(c, 0, sizeof(*c)); }

static int integer(const char *s, int low, int high, int *out) {
    char *end; long value;
    if (!*s) return 0;
    errno = 0; value = strtol(s, &end, 10);
    if (*end || errno == ERANGE || value < low || value > high) return 0;
    *out = (int)value; return 1;
}

static int hex(char ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'A' && ch <= 'F') return ch - 'A' + 10;
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    return -1;
}

static int real_value(const char *s, float *out) {
    char *end;
    errno = 0; *out = strtof(s, &end);
    return *s && !*end && errno != ERANGE && isfinite(*out);
}

static void fail(VisionClient *c, const char *reason) {
    c->failed = 1;
    snprintf(c->error, sizeof(c->error), "%s", reason);
}

static size_t request(VisionClient *c,uint16_t seq,const char *command,const char *args,
                      uint32_t now,uint32_t timeout,char *out,size_t capacity) {
    char body[96],packet[108]; int n,written;
    uint32_t errors=c->bad_frames; VisionTask task=c->task;
    if (!out || c->pending || !timeout) return 0;
    n=args?snprintf(body,sizeof(body),"V1,%u,%s,%s",(unsigned)seq,command,args):
           snprintf(body,sizeof(body),"V1,%u,%s",(unsigned)seq,command);
    if (n<0 || (size_t)n>=sizeof(body)) return 0;
    written=snprintf(packet,sizeof(packet),"$%s*%04X\r\n",body,(unsigned)vision_crc16((const uint8_t*)body,(size_t)n));
    if (written<0 || capacity<=(size_t)written) return 0;
    memcpy(out,packet,(size_t)written+1);
    vision_init(c); c->bad_frames=errors; c->task=task;
    c->seq=seq; c->pending=1; c->requested_ms=now; c->timeout_ms=timeout;
    snprintf(c->command,sizeof(c->command),"%s",command);
    return (size_t)written;
}
size_t vision_request(VisionClient *c,uint16_t seq,const char *command,
                      uint32_t now,uint32_t timeout,char *out,size_t capacity) {
    return vision_request_profile(c,seq,command,NULL,now,timeout,out,capacity);
}
size_t vision_request_profile(VisionClient *c,uint16_t seq,const char *command,const char *profile,
                              uint32_t now,uint32_t timeout,char *out,size_t capacity) {
    if (!command) return 0;
    if (strcmp(command,"COLOR") && strcmp(command,"RING") && strcmp(command,"QR") &&
        strcmp(command,"LOCATE") && strcmp(command,"STATUS") && strcmp(command,"RESET") &&
        strcmp(command,"RESUME") && strcmp(command,"STOP") && strcmp(command,"PING")) return 0;
    if (profile && strcmp(profile,"RAW") && strcmp(profile,"PROCESS") && strcmp(profile,"STORE") && strcmp(profile,"STACK")) return 0;
    if (profile && strcmp(command,"COLOR") && strcmp(command,"RING") && strcmp(command,"LOCATE")) return 0;
    return request(c,seq,command,profile,now,timeout,out,capacity);
}
size_t vision_ack_task(VisionClient *c,uint16_t seq,uint32_t now,uint32_t timeout,char *out,size_t capacity) {
    char args[16]; if (!c->task.valid) return 0;
    snprintf(args,sizeof(args),"%lu",(unsigned long)c->task.token);
    return request(c,seq,"TASK_ACK",args,now,timeout,out,capacity);
}
size_t vision_confirm_step(VisionClient *c,uint16_t seq,unsigned step,uint32_t now,
                           uint32_t timeout,char *out,size_t capacity) {
    char args[32]; if (!c->task.valid || step>=24) return 0;
    snprintf(args,sizeof(args),"%lu,%u",(unsigned long)c->task.token,step);
    size_t length=request(c,seq,"STEP",args,now,timeout,out,capacity);
    if (length) c->expected_step=(int)step;
    return length;
}
static int u32_value(const char *s,uint32_t *out) {
    char *end; unsigned long value;
    if (!*s || *s=='-') return 0;
    errno=0; value=strtoul(s,&end,10);
    if (*end || errno==ERANGE || value>UINT32_MAX) return 0;
    *out=(uint32_t)value; return 1;
}
size_t vision_home_done(VisionClient *c,uint16_t seq,uint32_t now,uint32_t timeout,char *out,size_t capacity) {
    char args[16]; if (!c->task.valid) return 0;
    snprintf(args,sizeof(args),"%lu",(unsigned long)c->task.token);
    return request(c,seq,"HOME_DONE",args,now,timeout,out,capacity);
}
static int parse_task(VisionTask *t,const char *raw,uint32_t token) {
    unsigned b,i,j; uint8_t masks[2]={0,0},slots[2]={0,0};
    if (strlen(raw)!=15 || raw[3]!='+' || raw[7]!='+' || raw[11]!='+' ||
        (uint16_t)token!=vision_crc16((const uint8_t*)raw,15)) return 0;
    memset(t,0,sizeof(*t));
    for (b=0;b<2;++b) for (i=0;i<3;++i) {
        int color=raw[b*8+i]-'0',slot=raw[b*8+4+i]-'0';
        if (color<1 || color>6 || slot<1 || slot>3 ||
            (masks[b]&(1u<<color)) || (slots[b]&(1u<<slot))) return 0;
        masks[b]|=(uint8_t)(1u<<color); slots[b]|=(uint8_t)(1u<<slot);
        t->color[b][i]=(uint8_t)color; t->process_slot[b][i]=(uint8_t)slot;
    }
    if (masks[0]!=masks[1]) return 0;
    for (i=0;i<3;++i) {
        t->store_slot[0][i]=t->process_slot[0][i];
        for (j=0;j<3;++j) if (t->color[1][i]==t->color[0][j]) t->store_slot[1][i]=t->store_slot[0][j];
    }
    memcpy(t->raw,raw,16); t->token=token; t->valid=1; t->updated=1; return 1;
}

static void parse(VisionClient *c) {
    char *star, *fields[20], *p; unsigned n = 0, j; int sequence, value;
    uint16_t received = 0;
    star = strrchr(c->rx, '*');
    if (!star || strlen(star+1) != 4) { c->bad_frames++; return; }
    for (j = 1; j <= 4; ++j) {
        int h = hex(star[j]);
        if (h < 0) { c->bad_frames++; return; }
        received = (uint16_t)((received << 4) | h);
    }
    if (vision_crc16((const uint8_t*)c->rx,(size_t)(star-c->rx)) != received) { c->bad_frames++; return; }
    *star = '\0'; p = c->rx;
    fields[n++] = p;
    while (*p) {
        if (*p == ',') {
            *p = '\0';
            if (n == 20) { c->bad_frames++; return; }
            fields[n++] = p+1;
        }
        ++p;
    }
    if (n < 3 || strcmp(fields[0],"V1") || !integer(fields[1],0,65535,&sequence)) { c->bad_frames++; return; }
    if (!strcmp(fields[2],"TASK")) {
        uint32_t token; VisionTask task;
        if (sequence!=0 || n!=5 || !u32_value(fields[3],&token) || !parse_task(&task,fields[4],token)) { c->bad_frames++; return; }
        if (c->task.valid && c->task.token==token && !strcmp(c->task.raw,task.raw)) return;
        /* New task while a previous one exists must not silently replace running actions. */
        if (c->task.valid) { fail(c,"TASK_CHANGED"); return; }
        c->task=task; return;
    }
    if (!c->pending || sequence != c->seq) return; /* Ignore stale or unsolicited results. */
    if (!strcmp(fields[2],"BLOCK") || !strcmp(fields[2],"RING") || !strcmp(fields[2],"ARUCO")) {
        VisionRecord r; int values[10];
        const char *expected=!strcmp(fields[2],"BLOCK")?"COLOR":fields[2];
        if (strcmp(c->command,expected) && (strcmp(c->command,"LOCATE") || !strcmp(fields[2],"ARUCO"))) { fail(c,"WRONG_MODE"); return; }
        if (n != 15 || c->count >= VISION_MAX_RECORDS) { fail(c,"BAD_RECORD"); return; }
        for (j=0;j<10;++j)
            if (!integer(fields[3+j],-1000000,1000000,&values[j])) { fail(c,"BAD_NUMBER"); return; }
        if (values[0] < 0 || values[0] > 49 || values[1] < 0 || values[1] >= 640 || values[2] < 0 || values[2] >= 480 ||
            values[5] < 0 || values[6] < 0 || values[6] > 3 ||
            values[7] < 0 || values[7] > 1 || values[8] < 0 || values[8] > 1 || values[9] < 0 || values[9] > 1) {
            fail(c,"BAD_RANGE"); return;
        }
        memset(&r,0,sizeof(r));
        snprintf(r.kind,sizeof(r.kind),"%s",fields[2]);
        r.id=values[0]; r.cx=values[1]; r.cy=values[2]; r.dx=values[3]; r.dy=values[4];
        r.pixels=values[5]; r.slot=values[6]; r.valid=(uint8_t)values[7];
        r.stable=(uint8_t)values[8]; r.calibrated=(uint8_t)values[9];
        if (r.calibrated) {
            if (!real_value(fields[13],&r.x_mm) || !real_value(fields[14],&r.y_mm)) { fail(c,"BAD_MM"); return; }
        } else if (strcmp(fields[13],"NA") || strcmp(fields[14],"NA")) { fail(c,"BAD_CAL"); return; }
        c->records[c->count++] = r;
    } else if (!strcmp(fields[2],"QR")) {
        size_t length;
        if (strcmp(c->command,"QR")) { fail(c,"WRONG_MODE"); return; }
        if (n != 6 || c->qr_present || !integer(fields[3],0,1,&value)) { fail(c,"BAD_QR"); return; }
        c->qr_valid = (uint8_t)value;
        if (!integer(fields[4],0,1,&value)) { fail(c,"BAD_QR"); return; }
        c->qr_stable = (uint8_t)value; length = strlen(fields[5]);
        if (length > 128 || length % 2) { fail(c,"BAD_QR"); return; }
        for (j=0;j<length/2;++j) {
            int a=hex(fields[5][2*j]), b=hex(fields[5][2*j+1]);
            if (a<0 || b<0 || (a==0 && b==0)) { fail(c,"BAD_QR"); return; }
            c->qr[j]=(char)((a<<4)|b);
        }
        c->qr[length/2]='\0'; c->qr_present=1;
    } else if (!strcmp(fields[2],"CONTEXT")) {
        uint32_t token;
        if (strcmp(c->command,"STATUS") || n!=13 || c->context_present || !u32_value(fields[4],&token) ||
            !integer(fields[5],0,24,&c->step) || !integer(fields[7],0,6,&c->target_color) ||
            !integer(fields[8],0,3,&c->target_slot) || !integer(fields[11],0,12,&c->grabs) ||
            !integer(fields[12],0,12,&c->places) || strlen(fields[3])>=sizeof(c->state) ||
            strlen(fields[6])>=sizeof(c->phase) || strlen(fields[9])>=sizeof(c->mode) || strlen(fields[10])>=sizeof(c->profile)) {
            fail(c,"BAD_CONTEXT"); return;
        }
        if (c->task.valid && token!=c->task.token) { fail(c,"TASK_MISMATCH"); return; }
        snprintf(c->state,sizeof(c->state),"%s",fields[3]); snprintf(c->phase,sizeof(c->phase),"%s",fields[6]);
        snprintf(c->mode,sizeof(c->mode),"%s",fields[9]); snprintf(c->profile,sizeof(c->profile),"%s",fields[10]);
        c->context_present=1;
    } else if (!strcmp(fields[2],"ACK_STEP")) {
        uint32_t token;
        if (n!=5 || strcmp(c->command,"STEP") || !u32_value(fields[3],&token) ||
            token!=c->task.token || !integer(fields[4],0,23,&c->ack_step) || c->ack_step!=c->expected_step) { fail(c,"BAD_ACK"); return; }
        c->ack=1; c->ack_token=token;
    } else if (!strcmp(fields[2],"ACK")) {
        uint32_t token;
        if (n!=4) { fail(c,"BAD_ACK"); return; }
        if (!strcmp(c->command,"TASK_ACK")) {
            if (!u32_value(fields[3],&token) || token!=c->task.token) { fail(c,"BAD_ACK"); return; }
            c->ack_token=token;
        } else if ((strcmp(c->command,"RESET") && strcmp(c->command,"RESUME") && strcmp(c->command,"HOME_DONE")) || strcmp(fields[3],c->command)) { fail(c,"BAD_ACK"); return; }
        c->ack=1;
        if (!strcmp(c->command,"RESET")) memset(&c->task,0,sizeof(c->task));
    } else if (!strcmp(fields[2],"DONE")) {
        char *end; unsigned long stamp;
        if (n != 5 || !integer(fields[3],0,6,&value)) { fail(c,"BAD_DONE"); return; }
        errno=0; stamp=strtoul(fields[4],&end,10);
        if (!*fields[4] || *end || *fields[4]=='-' || errno==ERANGE || stamp>UINT32_MAX) { fail(c,"BAD_TIME"); return; }
        if (value != c->count+c->qr_present+c->context_present) fail(c,"INCOMPLETE");
        if (value == 0 && !c->no_target && !c->pong && !c->stopped && !c->ack && !c->failed) fail(c,"INCOMPLETE");
        c->frame_ms=(uint32_t)stamp; c->pending=0; c->complete=1;
        if (c->failed) { c->count=0; c->qr_present=0; }
    } else if (!strcmp(fields[2],"ERROR")) {
        fail(c,n==4?fields[3]:"BAD_ERROR");
    } else if (!strcmp(fields[2],"NO_TARGET") || !strcmp(fields[2],"NO_MARKER") || !strcmp(fields[2],"NO_QR")) {
        if (n!=3) fail(c,"BAD_EMPTY"); else c->no_target=1;
    } else if (!strcmp(fields[2],"PONG")) {
        if (n!=6 || strcmp(c->command,"PING")) fail(c,"BAD_PONG"); else c->pong=1;
    } else if (!strcmp(fields[2],"STOPPED") && n==3 && !strcmp(c->command,"STOP")) c->stopped=1;
    else fail(c,"BAD_KIND");
}

void vision_feed(VisionClient *c, const uint8_t *bytes, size_t length) {
    size_t i;
    for (i=0;i<length;++i) {
        uint8_t byte=bytes[i];
        if (byte=='$') { c->rx_len=1; c->rx[0]='\0'; }
        else if (c->rx_len) {
            if (byte=='\n') {
                size_t n=c->rx_len-1;
                if (n && c->rx[n-1]=='\r') --n;
                c->rx[n]='\0'; parse(c); c->rx_len=0;
            } else if (c->rx_len < sizeof(c->rx) && (byte=='\r' || (byte>=32 && byte<=126))) {
                c->rx[c->rx_len++ - 1]=(char)byte;
            } else { c->rx_len=0; c->bad_frames++; }
        }
    }
}

void vision_tick(VisionClient *c, uint32_t now) {
    if (c->pending && (uint32_t)(now-c->requested_ms)>=c->timeout_ms) {
        c->pending=0; c->complete=0; c->timed_out=1; c->count=0; c->qr_present=0;
        fail(c,"TIMEOUT");
    }
}
