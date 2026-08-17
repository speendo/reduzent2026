#ifndef VOICE_H
#define VOICE_H

#include <stdint.h>
#include "envelope.h"

#define MAX_VOICES 8
#define VOICE_FREE_NOTE 0xFF

typedef struct {
    uint8_t note;            // MIDI note (0-127); VOICE_FREE_NOTE = free slot
    uint8_t velocity;        // note-on velocity 0-127
    env_stage_t stage;
    uint16_t level;          // current envelope level 0-127
    uint16_t release_start;  // level captured when release began
    uint32_t phase;          // 32-bit phase accumulator (used by path B mixer)
    uint32_t stage_start_ms; // ms timestamp when current stage began
    uint32_t born_ms;        // ms timestamp of note-on (oldest tiebreak)
} voice_t;

typedef struct {
    voice_t voices[MAX_VOICES];
    const envelope_params_t* env;
} voice_table_t;

static inline void voice_table_init(voice_table_t* vt, const envelope_params_t* env) {
    for (int i = 0; i < MAX_VOICES; i++) {
        vt->voices[i].note = VOICE_FREE_NOTE;
        vt->voices[i].velocity = 0;
        vt->voices[i].stage = ENV_STAGE_IDLE;
        vt->voices[i].level = 0;
        vt->voices[i].release_start = 0;
        vt->voices[i].phase = 0;
        vt->voices[i].stage_start_ms = 0;
        vt->voices[i].born_ms = 0;
    }
    vt->env = env;
}

static inline int voice_is_active(const voice_t* v) {
    return v->stage != ENV_STAGE_IDLE;
}

// Start (or retrigger) a note. Returns the voice index, or -1 if velocity is 0.
static inline int voice_note_on(voice_table_t* vt, uint8_t note, uint8_t velocity, uint32_t now_ms) {
    if (velocity == 0) return -1;

    // Retrigger an existing voice already sounding this note (release -> attack).
    for (int i = 0; i < MAX_VOICES; i++) {
        voice_t* v = &vt->voices[i];
        if (voice_is_active(v) && v->note == note) {
            v->velocity = velocity;
            v->stage = ENV_STAGE_ATTACK;
            v->level = 0;
            v->release_start = 0;
            v->stage_start_ms = now_ms;
            v->born_ms = now_ms;
            return i;
        }
    }

    // Claim a free voice.
    int idx = -1;
    for (int i = 0; i < MAX_VOICES; i++) {
        if (!voice_is_active(&vt->voices[i])) { idx = i; break; }
    }

    // No free voice: steal the quietest (then oldest).
    if (idx < 0) {
        uint16_t best_level = 0xFFFF;
        uint32_t best_born = 0xFFFFFFFF;
        for (int i = 0; i < MAX_VOICES; i++) {
            voice_t* v = &vt->voices[i];
            if (v->level < best_level || (v->level == best_level && v->born_ms < best_born)) {
                best_level = v->level;
                best_born = v->born_ms;
                idx = i;
            }
        }
    }

    voice_t* v = &vt->voices[idx];
    v->note = note;
    v->velocity = velocity;
    v->stage = ENV_STAGE_ATTACK;
    v->level = 0;
    v->release_start = 0;
    v->phase = 0;
    v->stage_start_ms = now_ms;
    v->born_ms = now_ms;
    return idx;
}

// Release the voice(s) sounding `note`. Returns 1 if a voice was released.
static inline int voice_note_off(voice_table_t* vt, uint8_t note, uint32_t now_ms) {
    int released = 0;
    for (int i = 0; i < MAX_VOICES; i++) {
        voice_t* v = &vt->voices[i];
        if (voice_is_active(v) && v->note == note && v->stage != ENV_STAGE_RELEASE) {
            v->release_start = v->level;
            v->stage = ENV_STAGE_RELEASE;
            v->stage_start_ms = now_ms;
            released = 1;
        }
    }
    return released;
}

// Advance every active voice's envelope by one tick.
static inline void voice_tick(voice_table_t* vt, uint32_t now_ms) {
    for (int i = 0; i < MAX_VOICES; i++) {
        voice_t* v = &vt->voices[i];
        if (!voice_is_active(v)) continue;
        envelope_advance(vt->env, v->velocity, &v->stage, &v->level,
                         &v->release_start, &v->stage_start_ms, now_ms);
        if (v->stage == ENV_STAGE_IDLE) {
            v->note = VOICE_FREE_NOTE;
            v->level = 0;
        }
    }
}

static inline uint8_t voice_active_count(const voice_table_t* vt) {
    uint8_t n = 0;
    for (int i = 0; i < MAX_VOICES; i++) {
        if (voice_is_active(&vt->voices[i])) n++;
    }
    return n;
}

// Next active voice after `from` (wrapping); returns index or -1 if none.
static inline int voice_arpeggio_step(const voice_table_t* vt, int from) {
    for (int step = 1; step <= MAX_VOICES; step++) {
        int i = (from + step) % MAX_VOICES;
        if (voice_is_active(&vt->voices[i])) return i;
    }
    return -1;
}

// Monophonic "current voice" (last-note-wins with release fallback).
// Among held voices (active, not RELEASE), return the most recently pressed
// (max born_ms). If none are held, return the most recently pressed RELEASE
// voice so the final note rings its tail. Returns -1 if no active voice.
static inline int voice_mono_current(const voice_table_t* vt) {
    int best = -1;
    uint32_t best_born = 0;
    for (int i = 0; i < MAX_VOICES; i++) {
        const voice_t* v = &vt->voices[i];
        if (v->stage == ENV_STAGE_IDLE || v->stage == ENV_STAGE_RELEASE) continue;
        if (v->born_ms >= best_born) { best = i; best_born = v->born_ms; }
    }
    if (best >= 0) return best;
    for (int i = 0; i < MAX_VOICES; i++) {
        const voice_t* v = &vt->voices[i];
        if (v->stage != ENV_STAGE_RELEASE) continue;
        if (v->born_ms >= best_born) { best = i; best_born = v->born_ms; }
    }
    return best;
}

#endif
