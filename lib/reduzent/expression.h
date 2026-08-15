#ifndef EXPRESSION_H
#define EXPRESSION_H

#include <stdint.h>
#include <math.h>

#define PITCH_BEND_CENTER 8192
#define PITCH_BEND_MAX    16383

// 14-bit pitch bend -> signed cents. `range_semitones` is the full-scale bend
// (leaf-spec default 2). Center (8192) = 0; 0 = -range; 16383 = +range.
static inline int16_t pitch_bend_cents(uint16_t bend, uint8_t range_semitones) {
    if (bend > PITCH_BEND_MAX) bend = PITCH_BEND_MAX;
    int32_t delta = (int32_t)bend - PITCH_BEND_CENTER; // [-8192, 8191]
    return (int16_t)((int32_t)range_semitones * 100 * delta / (int32_t)PITCH_BEND_CENTER);
}

// Vibrato LFO: 6 Hz sine, depth 0-50 cents from CC1 (0-127). Signed cents.
static inline int16_t vibrato_cents(uint32_t time_ms, uint8_t cc1_depth) {
    if (cc1_depth == 0) return 0;
    int16_t depth = (int16_t)((uint32_t)cc1_depth * 50 / 127);
    float phase = (float)time_ms / 1000.0f * 2.0f * 3.14159265f * 6.0f;
    return (int16_t)(depth * sinf(phase));
}

// Shift a frequency by `cents` (positive or negative); clamps to 1..65535.
static inline uint16_t cents_to_freq(uint16_t freq, int16_t cents) {
    float mult = powf(2.0f, (float)cents / 1200.0f);
    uint32_t out = (uint32_t)((float)freq * mult + 0.5f);
    if (out < 1) out = 1;
    if (out > 0xFFFF) out = 0xFFFF;
    return (uint16_t)out;
}

// Scale a 0-127 amplitude by a 0-127 factor (127 = full, 0 = mute), rounded.
static inline uint8_t scale_level(uint8_t level, uint8_t scale) {
    return (uint8_t)(((uint16_t)level * scale + 63) / 127);
}

#endif
