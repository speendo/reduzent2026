#ifndef MODE_H
#define MODE_H

#include <stdint.h>
#include <stdbool.h>

typedef enum { MODE_LIVE, MODE_SETTINGS } device_mode_t;

typedef struct {
    device_mode_t mode;
    uint32_t      settings_start_ms;   // millis() when settings entered
    uint32_t      settings_window_ms;  // timeout duration; 0 = settings disabled
} mode_state_t;

// Initialize to MODE_LIVE with the settings-window timeout in ms.
static inline void mode_init(mode_state_t* s, uint32_t settings_window_ms) {
    s->mode = MODE_LIVE;
    s->settings_start_ms = 0;
    s->settings_window_ms = settings_window_ms;
}

// Switch to MODE_SETTINGS and record the entry time.
static inline void mode_enter_settings(mode_state_t* s, uint32_t now) {
    s->mode = MODE_SETTINGS;
    s->settings_start_ms = now;
}

// Switch back to MODE_LIVE.
static inline void mode_exit_settings(mode_state_t* s) {
    s->mode = MODE_LIVE;
}

// Controller boot window: enter settings at boot iff the window is > 0.
// Returns true if it entered settings mode.
static inline bool mode_boot(mode_state_t* s, uint32_t now) {
    if (s->settings_window_ms > 0) {
        mode_enter_settings(s, now);
        return true;
    }
    return false;
}

// Advance the mode timer. A window of 0 disables settings (any entry is undone
// on the next tick); otherwise auto-exit to live once the window expires.
// Returns true if the mode changed.
static inline bool mode_tick(mode_state_t* s, uint32_t now) {
    if (s->mode == MODE_SETTINGS) {
        if (s->settings_window_ms == 0 ||
            (int32_t)(now - s->settings_start_ms) >= (int32_t)s->settings_window_ms) {
            mode_exit_settings(s);
            return true;
        }
    }
    return false;
}

static inline bool mode_is_settings(const mode_state_t* s) {
    return s->mode == MODE_SETTINGS;
}

#endif
