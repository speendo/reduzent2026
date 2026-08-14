#ifndef ESPNOW_FRAME_H
#define ESPNOW_FRAME_H

#include <stdint.h>

#define ESP_NOW_FRAME_SIZE 5
#define ESP_NOW_CHANNEL_BROADCAST 0xFF

typedef enum {
    EVENT_NOTE = 0,
    EVENT_PITCH_BEND = 1,
    EVENT_CHANNEL_AFTERTOUCH = 2,
    EVENT_POLY_AFTERTOUCH = 3,
    EVENT_PROGRAM_CHANGE = 4,
    EVENT_CC1_VIBRATO = 5,
    EVENT_PANIC = 6,
    EVENT_ENTER_SETTINGS = 7,
} espnow_event_type_t;

// Fixed 5-byte frame, channel-first (leaf filters on byte 0).
typedef struct {
    uint8_t channel;   // target node 0-15, or 0xFF = all leaves
    uint8_t type;      // espnow_event_type_t
    uint8_t note;      // NOTE / POLY_AFTERTOUCH only
    uint8_t value;     // velocity / pressure / program / depth / bend LSB
    uint8_t value_hi;  // pitch-bend MSB only
} espnow_frame_t;

static inline void frame_pack(const espnow_frame_t* f, uint8_t out[ESP_NOW_FRAME_SIZE]) {
    out[0] = f->channel;
    out[1] = f->type;
    out[2] = f->note;
    out[3] = f->value;
    out[4] = f->value_hi;
}

static inline void frame_unpack(const uint8_t in[ESP_NOW_FRAME_SIZE], espnow_frame_t* f) {
    f->channel = in[0];
    f->type = in[1];
    f->note = in[2];
    f->value = in[3];
    f->value_hi = in[4];
}

#endif
