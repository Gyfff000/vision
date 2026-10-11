#ifndef VISION_CLIENT_H
#define VISION_CLIENT_H
#include <stddef.h>
#include <stdint.h>

/* Portable C99, no MCU/HAL dependencies. Feed bytes from main/task, not ISR. */
#define VISION_MAX_RECORDS 6
typedef struct {
    char kind[8];
    int id, cx, cy, dx, dy, pixels, slot;
    uint8_t valid, stable, calibrated;
    float x_mm, y_mm; /* meaningful only if calibrated == 1 */
} VisionRecord;

typedef struct {
    uint16_t seq;
    uint8_t pending, complete, failed, timed_out, no_target, pong, stopped;
    char command[8];
    uint8_t count, qr_present, qr_valid, qr_stable;
    char qr[65];
    char error[32];
    VisionRecord records[VISION_MAX_RECORDS];
    uint32_t requested_ms, timeout_ms, frame_ms;
    uint32_t bad_frames;
    char rx[249];
    uint16_t rx_len;
} VisionClient;

uint16_t vision_crc16(const uint8_t *data, size_t length);
void vision_init(VisionClient *client);
/* Request accepts PING/COLOR/RING/ARUCO/QR/STOP; 0 means invalid/busy/no space. */
size_t vision_request(VisionClient *client, uint16_t seq, const char *command,
                      uint32_t now_ms, uint32_t timeout_ms, char *out, size_t capacity);
size_t vision_request_profile(VisionClient *client, uint16_t seq, const char *command,
                              const char *profile, uint32_t now_ms, uint32_t timeout_ms,
                              char *out, size_t capacity);
void vision_feed(VisionClient *client, const uint8_t *bytes, size_t length);
void vision_tick(VisionClient *client, uint32_t now_ms);
#endif
