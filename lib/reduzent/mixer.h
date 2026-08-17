#ifndef MIXER_H
#define MIXER_H

#include <stdint.h>
#include "voice.h"

#define MIXER_SAMPLE_RATE 32000  // Hz (leaf-spec 1-bit sample rate)

// Phase increment for a square wave at `freq` Hz sampled at `sample_rate` Hz:
// phaseIncrement = freq * 2^32 / sample_rate (64-bit intermediate).
static inline uint32_t phase_increment(uint16_t freq, uint32_t sample_rate) {
    return (uint32_t)(((uint64_t)freq << 32) / sample_rate);
}

// Advance one voice's 32-bit phase and return its 1-bit output: high when
// phase < (level << 24), i.e. duty = level/256 (square wave; level 0 = off).
// `inc` is the precomputed phase increment for this voice (expression applied).
static inline uint8_t voice_sample_bit(voice_t* v, uint32_t inc) {
    v->phase += inc;
    return (v->phase < ((uint32_t)v->level << 24)) ? 1 : 0;
}

// XOR all active voices into one output bit. `inc[i]` is the precomputed phase
// increment for voice i (0 for idle voices).
static inline uint8_t mix_voices(voice_table_t* vt, const uint32_t inc[MAX_VOICES]) {
    uint8_t out = 0;
    for (int i = 0; i < MAX_VOICES; i++) {
        voice_t* v = &vt->voices[i];
        if (!voice_is_active(v)) continue;
        out ^= voice_sample_bit(v, inc[i]);
    }
    return out;
}

#endif
