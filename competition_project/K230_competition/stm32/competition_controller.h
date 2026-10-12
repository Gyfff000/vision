#ifndef COMPETITION_CONTROLLER_H
#define COMPETITION_CONTROLLER_H
#include "vision_client.h"

typedef struct {
    unsigned index;
    const char *phase, *mode, *profile;
    uint8_t color, slot, pick, stack;
} CompetitionStep;

/* Robot callbacks must report measured completion. Never return success simply
   because a command was transmitted. prepare includes navigation/camera pose;
   pick action includes placing the grabbed object onto the vehicle. */
typedef struct {
    void (*send)(const uint8_t *, size_t);
    void (*prepare_start)(const CompetitionStep *);
    int (*prepare_poll)(void); /* -1 error, 0 busy, 1 confirmed */
    void (*action_start)(const CompetitionStep *, const VisionRecord *);
    int (*action_poll)(void);
    void (*home_start)(void);
    int (*home_poll)(void);
    void (*stop)(void);
} CompetitionIO;

enum { CC_WAIT_TASK, CC_ACK, CC_PREPARE, CC_LOCATE, CC_ACTION, CC_STEP,
       CC_HOME, CC_FINISHED, CC_FAULT, CC_FINAL_ACK, CC_WAIT_START, CC_RESET };
typedef struct {
    VisionClient vision;
    CompetitionIO io;
    CompetitionStep current;
    unsigned state, step, retries, grabs, places;
    uint16_t seq;
    uint32_t stage_ms, last_request_ms;
    uint32_t request_timeout_ms, motion_timeout_ms, locate_timeout_ms;
    uint32_t max_result_latency_ms;
    uint8_t require_mm;
    char error[32];
} CompetitionController;

int competition_step(const VisionTask *, unsigned index, CompetitionStep *);
int competition_init(CompetitionController *, const CompetitionIO *);
/* Call once from the labelled start button. Resets stale task before motion. */
int competition_start(CompetitionController *, uint32_t now_ms);
void competition_feed(CompetitionController *, const uint8_t *, size_t);
void competition_tick(CompetitionController *, uint32_t now_ms);
void competition_abort(CompetitionController *, const char *reason);
#endif
