#include "vision_client.h"
#include <stdio.h>
#include <stdlib.h>
int main(int argc,char **argv) {
    VisionClient c; char tx[80]; FILE *in; int byte; size_t length;
    if (argc!=4 && argc!=5) return 2;
    vision_init(&c);
    length=vision_request_profile(&c,42,argv[2],argc==5?argv[4]:NULL,0xFFFFFF00u,1000,tx,sizeof(tx));
    if (!length) return 3;
    printf("TX %s",tx);
    in=fopen(argv[1],"rb"); if (!in) return 4;
    while ((byte=fgetc(in))!=EOF) { uint8_t b=(uint8_t)byte; vision_feed(&c,&b,1); }
    fclose(in);
    if (atoi(argv[3])) vision_tick(&c,0x00000300u); /* Timer wraparound. */
    printf("STATE %u %u %u %u %u %u %u %u %lu %s\n",
           c.pending,c.complete,c.failed,c.timed_out,c.count,c.qr_present,
           c.qr_valid,c.qr_stable,(unsigned long)c.bad_frames,c.error);
    if (c.count) printf("RECORD %s %d %d %d %d %.3f %.3f\n",c.records[0].kind,
                        c.records[0].id,c.records[0].cx,c.records[0].valid,
                        c.records[0].calibrated,(double)c.records[0].x_mm,(double)c.records[0].y_mm);
    if (c.qr_present) printf("QR %s\n",c.qr);
    return 0;
}
