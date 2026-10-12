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
    uint32_t token;
    char raw[16];
    uint8_t valid, updated;
    uint8_t color[2][3], process_slot[2][3], store_slot[2][3];
} VisionTask;

typedef struct {
    uint16_t seq;
    uint8_t pending, complete, failed, timed_out, no_target, pong, stopped;
    char command[12];
    VisionTask task; /* Persistent across requests; event TASK uses seq=0. */
    uint8_t ack, context_present;
    char state[12], phase[20], mode[8], profile[12];
    int step, target_color, target_slot, grabs, places;
    uint32_t ack_token;
    int ack_step, expected_step;
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
/* Request accepts PING/STATUS/LOCATE/COLOR/RING/QR/STOP/RESUME/RESET. */
size_t vision_request(VisionClient *client, uint16_t seq, const char *command,
                      uint32_t now_ms, uint32_t timeout_ms, char *out, size_t capacity);
size_t vision_request_profile(VisionClient *client, uint16_t seq, const char *command,
                              const char *profile, uint32_t now_ms, uint32_t timeout_ms,
                              char *out, size_t capacity);
size_t vision_ack_task(VisionClient *c, uint16_t seq, uint32_t now, uint32_t timeout,
                       char *out, size_t capacity);
size_t vision_confirm_step(VisionClient *c, uint16_t seq, unsigned step, uint32_t now,
                           uint32_t timeout, char *out, size_t capacity);
size_t vision_home_done(VisionClient *c, uint16_t seq, uint32_t now, uint32_t timeout,
                        char *out, size_t capacity);
void vision_feed(VisionClient *client, const uint8_t *bytes, size_t length);
void vision_tick(VisionClient *client, uint32_t now_ms);
#endif
