#ifndef ENVELOPE_H
#define ENVELOPE_H

#include <stdint.h>

typedef enum {
    ENV_STAGE_IDLE = 0,     // voice is free / silent
    ENV_STAGE_ATTACK = 1,
    ENV_STAGE_DECAY = 2,
    ENV_STAGE_SUSTAIN = 3,
    ENV_STAGE_RELEASE = 4,
} env_stage_t;

typedef struct {
    uint16_t attack_ms;
    uint16_t decay_ms;
    uint16_t release_ms;
    uint8_t  sustain_pct;   // 0-100, percentage of velocity
} envelope_params_t;

// Defaults per leaf-spec: A5 / D100 / S70% / R100 ms.
static const envelope_params_t ENVELOPE_DEFAULT = { 5, 100, 100, 70 };

// Advance one voice's envelope in place. `level` (0-127) and `stage` are
// updated; a voice that finishes releasing becomes ENV_STAGE_IDLE with level 0.
// `release_start` is the level captured when the voice entered RELEASE (kept by
// the caller across ticks). A zero-duration stage transitions immediately.
static inline void envelope_advance(const envelope_params_t* p,
                                    uint8_t velocity,
                                    env_stage_t* stage,
                                    uint16_t* level,
                                    uint16_t* release_start,
                                    uint32_t* stage_start_ms,
                                    uint32_t now_ms) {
    if (*stage == ENV_STAGE_IDLE) { *level = 0; return; }

    uint32_t elapsed = now_ms - *stage_start_ms;

    while (1) {
        switch (*stage) {
            case ENV_STAGE_ATTACK: {
                uint16_t a = p->attack_ms;
                if (a == 0 || elapsed >= a) {
                    *level = velocity;
                    *stage = ENV_STAGE_DECAY;
                    *stage_start_ms = now_ms;
                    elapsed = 0;
                    continue;
                }
                *level = (uint16_t)((uint32_t)velocity * elapsed / a);
                return;
            }
            case ENV_STAGE_DECAY: {
                uint16_t sustain = (uint16_t)((uint32_t)velocity * p->sustain_pct / 100);
                uint16_t d = p->decay_ms;
                if (d == 0 || elapsed >= d) {
                    *level = sustain;
                    *stage = ENV_STAGE_SUSTAIN;
                    *stage_start_ms = now_ms;
                    elapsed = 0;
                    continue;
                }
                *level = (uint16_t)(velocity - (uint16_t)((uint32_t)(velocity - sustain) * elapsed / d));
                return;
            }
            case ENV_STAGE_SUSTAIN: {
                *level = (uint16_t)((uint32_t)velocity * p->sustain_pct / 100);
                return;
            }
            case ENV_STAGE_RELEASE: {
                uint16_t r = p->release_ms;
                if (r == 0 || elapsed >= r) {
                    *level = 0;
                    *stage = ENV_STAGE_IDLE;
                } else {
                    *level = (uint16_t)((uint32_t)*release_start * (r - elapsed) / r);
                }
                return;
            }
            default:
                *level = 0;
                return;
        }
    }
}

#endif
