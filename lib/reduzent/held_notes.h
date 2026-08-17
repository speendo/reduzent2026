#ifndef HELD_NOTES_H
#define HELD_NOTES_H

#include <stdint.h>

#define HELD_CHANNELS 16
#define HELD_NOTES 128

typedef struct {
    uint8_t vel[HELD_CHANNELS][HELD_NOTES];
} held_notes_t;

static inline void held_notes_init(held_notes_t* h) {
    for (int ch = 0; ch < HELD_CHANNELS; ch++)
        for (int n = 0; n < HELD_NOTES; n++)
            h->vel[ch][n] = 0;
}

static inline void held_set(held_notes_t* h, uint8_t ch, uint8_t note, uint8_t vel) {
    if (ch >= HELD_CHANNELS || note >= HELD_NOTES) return;
    h->vel[ch][note] = vel;
}

static inline void held_clear(held_notes_t* h, uint8_t ch, uint8_t note) {
    if (ch >= HELD_CHANNELS || note >= HELD_NOTES) return;
    h->vel[ch][note] = 0;
}

static inline void held_clear_channel(held_notes_t* h, uint8_t ch) {
    if (ch >= HELD_CHANNELS) return;
    for (int n = 0; n < HELD_NOTES; n++) h->vel[ch][n] = 0;
}

static inline void held_clear_all(held_notes_t* h) {
    for (int ch = 0; ch < HELD_CHANNELS; ch++) held_clear_channel(h, ch);
}

static inline int held_next(const held_notes_t* h, uint16_t* cursor,
                            uint8_t* ch_out, uint8_t* note_out, uint8_t* vel_out) {
    uint16_t total = HELD_CHANNELS * HELD_NOTES;
    for (uint16_t i = *cursor; i < total; i++) {
        uint8_t ch = (uint8_t)(i / HELD_NOTES);
        uint8_t note = (uint8_t)(i % HELD_NOTES);
        if (h->vel[ch][note] != 0) {
            *ch_out = ch;
            *note_out = note;
            *vel_out = h->vel[ch][note];
            *cursor = (uint16_t)(i + 1);
            return 1;
        }
    }
    *cursor = total;
    return 0;
}

#endif
