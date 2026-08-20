#ifndef MODE_H
#define MODE_H

#include <stdint.h>
#include <stdbool.h>

#define MODE_GRACE_MS 7000  // grace period after last client disconnects

typedef enum { MODE_LIVE, MODE_SETTINGS } device_mode_t;

typedef struct {
    device_mode_t mode;
    uint32_t      settings_start_ms;   // millis() when settings entered
    uint32_t      settings_window_ms;  // timeout duration; 0 = settings disabled
    uint8_t       client_count;        // WiFi AP clients currently connected
    uint32_t      grace_start_ms;      // millis() when grace period started; 0 = not in grace
    bool          exit_requested;      // set by "leave settings" UI action
} mode_state_t;

// Initialize to MODE_LIVE with the settings-window timeout in ms.
static inline void mode_init(mode_state_t* s, uint32_t settings_window_ms) {
    s->mode = MODE_LIVE;
    s->settings_start_ms = 0;
    s->settings_window_ms = settings_window_ms;
    s->client_count = 0;
    s->grace_start_ms = 0;
    s->exit_requested = false;
}

// Switch to MODE_SETTINGS and record the entry time.
static inline void mode_enter_settings(mode_state_t* s, uint32_t now) {
    s->mode = MODE_SETTINGS;
    s->settings_start_ms = now;
    s->grace_start_ms = 0;
    s->exit_requested = false;
}

// Switch back to MODE_LIVE.
static inline void mode_exit_settings(mode_state_t* s) {
    s->mode = MODE_LIVE;
    s->grace_start_ms = 0;
    s->exit_requested = false;
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

// Update AP client count. When the last client disconnects, start the grace
// period. When a client connects during grace, cancel it.
static inline void mode_set_clients(mode_state_t* s, uint8_t count, uint32_t now) {
    uint8_t prev = s->client_count;
    s->client_count = count;

    if (s->mode != MODE_SETTINGS) return;

    if (prev > 0 && count == 0) {
        // Last client disconnected — start grace period
        s->grace_start_ms = now;
    } else if (prev == 0 && count > 0 && s->grace_start_ms != 0) {
        // Client reconnected during grace — cancel it
        s->grace_start_ms = 0;
    }
}

// Request exit from settings mode (triggered by parasol "leave" checkbox).
static inline void mode_request_exit(mode_state_t* s) {
    s->exit_requested = true;
}

// Advance the mode timer. Behavior:
//   - If no clients connected and no grace period: count down the timeout
//   - If clients connected: pause (stay indefinitely)
//   - If grace period active: count down grace; exit when it expires
//   - If exit_requested: exit immediately
// Returns true if the mode changed.
static inline bool mode_tick(mode_state_t* s, uint32_t now) {
    if (s->mode != MODE_SETTINGS) return false;

    // Explicit exit request (parasol "leave" checkbox)
    if (s->exit_requested) {
        mode_exit_settings(s);
        return true;
    }

    // Clients connected — pause everything
    if (s->client_count > 0) return false;

    // Grace period active — count down
    if (s->grace_start_ms != 0) {
        if ((int32_t)(now - s->grace_start_ms) >= (int32_t)MODE_GRACE_MS) {
            mode_exit_settings(s);
            return true;
        }
        return false;
    }

    // No clients, no grace — count down the main timeout
    if (s->settings_window_ms == 0 ||
        (int32_t)(now - s->settings_start_ms) >= (int32_t)s->settings_window_ms) {
        mode_exit_settings(s);
        return true;
    }

    return false;
}

static inline bool mode_is_settings(const mode_state_t* s) {
    return s->mode == MODE_SETTINGS;
}

#endif
