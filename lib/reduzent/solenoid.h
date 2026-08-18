#ifndef SOLENOID_H
#define SOLENOID_H

#include <stdint.h>

// Percussive strike state for one solenoid leaf. A note-on matching `my_note`
// energizes the coil at `active_duty` until `active_until_ms`, then off.
// Note-off is ignored (percussive). No envelope — a striker needs force, not
// shaping. Timestamps come from millis() and are compared wraparound-safe.
typedef struct {
    uint8_t my_note;       // MIDI note that triggers this solenoid (0-127)
    uint8_t min_duty;      // duty at velocity 1 (0-255; calibrated on hardware)
    uint8_t max_duty;      // duty at velocity 127 (0-255; calibrated on hardware)
    uint16_t hold_ms;      // strike window duration
    uint32_t active_until_ms; // ms timestamp when the window closes; 0 = idle
    uint8_t active_duty;   // duty being output during the window
} solenoid_t;

static inline void solenoid_init(solenoid_t* s, uint8_t my_note,
                                 uint8_t min_duty, uint8_t max_duty,
                                 uint16_t hold_ms) {
    s->my_note = my_note;
    s->min_duty = min_duty;
    s->max_duty = max_duty;
    s->hold_ms = hold_ms;
    s->active_until_ms = 0;
    s->active_duty = 0;
}

static inline uint8_t solenoid_strike_duty(const solenoid_t* s, uint8_t velocity) {
    if (velocity == 0) return 0;
    if (velocity > 127) velocity = 127;
    uint32_t range = (uint32_t)s->max_duty - s->min_duty;
    uint32_t scaled = ((uint32_t)(velocity - 1) * range + 63) / 126;
    return (uint8_t)(s->min_duty + scaled);
}

static inline int solenoid_note_on(solenoid_t* s, uint8_t note, uint8_t velocity,
                                   uint32_t now_ms) {
    if (velocity == 0) return 0;
    if (note != s->my_note) return 0;
    s->active_duty = solenoid_strike_duty(s, velocity);
    s->active_until_ms = now_ms + s->hold_ms;
    return 1;
}

static inline uint8_t solenoid_tick(const solenoid_t* s, uint32_t now_ms) {
    if (s->active_until_ms == 0) return 0;
    if ((int32_t)(now_ms - s->active_until_ms) >= 0) return 0;
    return s->active_duty;
}

#endif
