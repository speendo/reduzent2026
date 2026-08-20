#ifndef ACTUATOR_H
#define ACTUATOR_H

#include <stdint.h>

// What to do with a note event (EVENT_NOTE) on a leaf, given its actuator type.
// A leaf hosts exactly one actuator: piezo leaves drive the voice table (note
// on/off), solenoid leaves strike on a matching note-on (note-off is ignored —
// percussive). cfg.actuator is 0 = piezo, 1 = solenoid.
typedef enum {
    NOTE_ACTION_NONE = 0,         // solenoid note-off: no-op
    NOTE_ACTION_PIEZO_ON,         // start/retrigger a voice
    NOTE_ACTION_PIEZO_OFF,        // release the voice(s)
    NOTE_ACTION_SOLENOID_STRIKE,  // energize the coil (note-match checked by the driver)
} note_action_t;

static inline note_action_t actuator_note_action(uint8_t actuator, uint8_t velocity) {
    if (actuator == 1) {
        return velocity == 0 ? NOTE_ACTION_NONE : NOTE_ACTION_SOLENOID_STRIKE;
    }
    return velocity == 0 ? NOTE_ACTION_PIEZO_OFF : NOTE_ACTION_PIEZO_ON;
}

#endif
