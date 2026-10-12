#include "competition_controller.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
static CompetitionController cc;
static void send_bytes(const uint8_t *data,size_t size) { printf("TX %.*s",(int)size,(const char*)data); }
static void prepare_start(const CompetitionStep *s) { printf("PREPARE %u %s %u %u\n",s->index,s->phase,s->color,s->slot); }
static int poll_success(void) { return 1; }
static void action_start(const CompetitionStep *s,const VisionRecord *r) { printf("ACTION %u %s %u %u %d\n",s->index,s->phase,s->color,s->slot,r->calibrated); }
static void home_start(void) { puts("HOME"); }
static void stop(void) { puts("STOP"); }
int main(void) {
    CompetitionIO io={send_bytes,prepare_start,poll_success,action_start,poll_success,home_start,poll_success,stop};
    char line[1024]; uint8_t bytes[512];
    if (!competition_init(&cc,&io)) return 2;
    while (fgets(line,sizeof(line),stdin)) {
        if (line[0]=='I') competition_init(&cc,&io);
        else if (line[0]=='B') competition_start(&cc,(uint32_t)strtoul(line+2,NULL,10));
        else if (line[0]=='R') {
            size_t i,n=strcspn(line+2,"\r\n")/2;
            for(i=0;i<n;++i) { unsigned value; if (sscanf(line+2+i*2,"%2x",&value)!=1) return 3; bytes[i]=(uint8_t)value; }
            competition_feed(&cc,bytes,n);
        } else if (line[0]=='T') competition_tick(&cc,(uint32_t)strtoul(line+2,NULL,10));
        printf("STATE %u %u %s\nEND\n",cc.state,cc.step,cc.error); fflush(stdout);
    }
    return 0;
}
