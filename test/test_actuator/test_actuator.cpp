#include <unity.h>
#include "actuator.h"

void setUp(void) {}
void tearDown(void) {}

// === Actuator note dispatch ===
// A note-on/off (EVENT_NOTE) must be routed by the leaf's actuator type:
// piezo leaves drive the voice table, solenoid leaves strike on a matching
// note-on (note-off is ignored, percussive). Regression: the solenoid driver
// dropped the piezo branch, so piezo notes only started on the 750 ms
// keepalive. This helper must lock the piezo path back in.

void test_piezo_note_on_dispatches_to_voice(void) {
    TEST_ASSERT_EQUAL(NOTE_ACTION_PIEZO_ON,
                      actuator_note_action(0, 100));
}

void test_piezo_note_off_dispatches_to_voice(void) {
    TEST_ASSERT_EQUAL(NOTE_ACTION_PIEZO_OFF,
                      actuator_note_action(0, 0));
}

void test_solenoid_note_on_dispatches_to_strike(void) {
    TEST_ASSERT_EQUAL(NOTE_ACTION_SOLENOID_STRIKE,
                      actuator_note_action(1, 100));
}

void test_solenoid_note_off_is_ignored(void) {
    TEST_ASSERT_EQUAL(NOTE_ACTION_NONE,
                      actuator_note_action(1, 0));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_piezo_note_on_dispatches_to_voice);
    RUN_TEST(test_piezo_note_off_dispatches_to_voice);
    RUN_TEST(test_solenoid_note_on_dispatches_to_strike);
    RUN_TEST(test_solenoid_note_off_is_ignored);
    return UNITY_END();
}
