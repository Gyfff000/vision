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

size_t vision_request(VisionClient *c, uint16_t seq, const char *command,
                      uint32_t now, uint32_t timeout, char *out, size_t capacity) {
    return vision_request_profile(c,seq,command,NULL,now,timeout,out,capacity);
}

size_t vision_request_profile(VisionClient *c, uint16_t seq, const char *command,
                              const char *profile, uint32_t now, uint32_t timeout,
                              char *out, size_t capacity) {
    char body[40], packet[50]; int n, written; uint32_t errors = c->bad_frames;
    if (!command || !out || c->pending || timeout == 0) return 0;
    if (strcmp(command,"COLOR") && strcmp(command,"RING") && strcmp(command,"QR") &&
        strcmp(command,"ARUCO") && strcmp(command,"STOP") && strcmp(command,"PING")) return 0;
    if (profile && (strcmp(profile,"GRASP") && strcmp(profile,"PLACE") && strcmp(profile,"STACK"))) return 0;
    if (profile && strcmp(command,"COLOR") && strcmp(command,"RING") && strcmp(command,"ARUCO")) return 0;
    n = profile ? snprintf(body,sizeof(body),"V1,%u,%s,%s",(unsigned)seq,command,profile) :
                  snprintf(body,sizeof(body),"V1,%u,%s",(unsigned)seq,command);
    if (n < 0 || (size_t)n >= sizeof(body)) return 0;
    written = snprintf(packet,sizeof(packet),"$%s*%04X\r\n",body,
                       (unsigned)vision_crc16((const uint8_t*)body,(size_t)n));
    if (written < 0 || (size_t)written >= sizeof(packet) || capacity <= (size_t)written) return 0;
    memcpy(out,packet,(size_t)written+1);
    vision_init(c); c->bad_frames = errors;
    c->seq = seq; c->pending = 1; c->requested_ms = now; c->timeout_ms = timeout;
    snprintf(c->command,sizeof(c->command),"%s",command);
    return (size_t)written;
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
    if (!c->pending || sequence != c->seq) return; /* Ignore stale or unsolicited results. */
    if (!strcmp(fields[2],"BLOCK") || !strcmp(fields[2],"RING") || !strcmp(fields[2],"ARUCO")) {
        VisionRecord r; int values[10];
        const char *expected=!strcmp(fields[2],"BLOCK")?"COLOR":fields[2];
        if (strcmp(c->command,expected)) { fail(c,"WRONG_MODE"); return; }
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
    } else if (!strcmp(fields[2],"DONE")) {
        char *end; unsigned long stamp;
        if (n != 5 || !integer(fields[3],0,6,&value)) { fail(c,"BAD_DONE"); return; }
        errno=0; stamp=strtoul(fields[4],&end,10);
        if (!*fields[4] || *end || *fields[4]=='-' || errno==ERANGE || stamp>UINT32_MAX) { fail(c,"BAD_TIME"); return; }
        if (value != c->count+c->qr_present) fail(c,"INCOMPLETE");
        if (value == 0 && !c->no_target && !c->pong && !c->stopped && !c->failed) fail(c,"INCOMPLETE");
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
