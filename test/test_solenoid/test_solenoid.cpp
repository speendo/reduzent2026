#include <unity.h>
#include "solenoid.h"

void setUp(void) {}
void tearDown(void) {}

static void make_default(solenoid_t* s) {
    solenoid_init(s, 60, 40, 220, 40);
}

// === Task 1: init + duty scaling ===

void test_init_sets_defaults(void) {
    solenoid_t s;
    make_default(&s);
    TEST_ASSERT_EQUAL_UINT8(60, s.my_note);
    TEST_ASSERT_EQUAL_UINT8(40, s.min_duty);
    TEST_ASSERT_EQUAL_UINT8(220, s.max_duty);
    TEST_ASSERT_EQUAL_UINT16(40, s.hold_ms);
    TEST_ASSERT_EQUAL_UINT32(0, s.active_until_ms);
    TEST_ASSERT_EQUAL_UINT8(0, s.active_duty);
}

void test_duty_at_velocity_1(void) {
    solenoid_t s;
    make_default(&s);
    TEST_ASSERT_EQUAL_UINT8(40, solenoid_strike_duty(&s, 1));
}

void test_duty_at_velocity_127(void) {
    solenoid_t s;
    make_default(&s);
    TEST_ASSERT_EQUAL_UINT8(220, solenoid_strike_duty(&s, 127));
}

void test_duty_at_velocity_64(void) {
    solenoid_t s;
    make_default(&s);
    TEST_ASSERT_EQUAL_UINT8(130, solenoid_strike_duty(&s, 64));
}

void test_duty_velocity_0_is_zero(void) {
    solenoid_t s;
    make_default(&s);
    TEST_ASSERT_EQUAL_UINT8(0, solenoid_strike_duty(&s, 0));
}

void test_duty_velocity_over_127_clamps(void) {
    solenoid_t s;
    make_default(&s);
    TEST_ASSERT_EQUAL_UINT8(220, solenoid_strike_duty(&s, 200));
}

void test_duty_monotonic(void) {
    solenoid_t s;
    make_default(&s);
    uint8_t prev = 0;
    for (uint8_t v = 1; v <= 127; v++) {
        uint8_t d = solenoid_strike_duty(&s, v);
        TEST_ASSERT_TRUE(d >= prev);
        prev = d;
    }
}

// === Task 2: retrigger + note-off ===

void test_note_on_matching_note_strikes(void) {
    solenoid_t s;
    make_default(&s);
    TEST_ASSERT_EQUAL(1, solenoid_note_on(&s, 60, 64, 1000));
    TEST_ASSERT_EQUAL_UINT32(1040, s.active_until_ms);
    TEST_ASSERT_EQUAL_UINT8(130, s.active_duty);
}

void test_note_on_non_matching_note_ignored(void) {
    solenoid_t s;
    make_default(&s);
    TEST_ASSERT_EQUAL(0, solenoid_note_on(&s, 67, 100, 1000));
    TEST_ASSERT_EQUAL_UINT32(0, s.active_until_ms);
    TEST_ASSERT_EQUAL_UINT8(0, s.active_duty);
}

void test_note_off_ignored(void) {
    solenoid_t s;
    make_default(&s);
    solenoid_note_on(&s, 60, 64, 1000);
    TEST_ASSERT_EQUAL(0, solenoid_note_on(&s, 60, 0, 1005));
    TEST_ASSERT_EQUAL_UINT32(1040, s.active_until_ms);
}

void test_retrigger_restarts_hold_window(void) {
    solenoid_t s;
    make_default(&s);
    solenoid_note_on(&s, 60, 64, 1000);
    TEST_ASSERT_EQUAL(1, solenoid_note_on(&s, 60, 127, 1030));
    TEST_ASSERT_EQUAL_UINT32(1070, s.active_until_ms);
    TEST_ASSERT_EQUAL_UINT8(220, s.active_duty);
}

// === Task 3: hold-window timing ===

void test_tick_idle_returns_zero(void) {
    solenoid_t s;
    make_default(&s);
    TEST_ASSERT_EQUAL_UINT8(0, solenoid_tick(&s, 0));
    TEST_ASSERT_EQUAL_UINT8(0, solenoid_tick(&s, 5000));
}

void test_tick_within_window_returns_duty(void) {
    solenoid_t s;
    make_default(&s);
    solenoid_note_on(&s, 60, 64, 1000);
    TEST_ASSERT_EQUAL_UINT8(130, solenoid_tick(&s, 1000));
    TEST_ASSERT_EQUAL_UINT8(130, solenoid_tick(&s, 1039));
}

void test_tick_after_window_closes_returns_zero(void) {
    solenoid_t s;
    make_default(&s);
    solenoid_note_on(&s, 60, 64, 1000);
    TEST_ASSERT_EQUAL_UINT8(0, solenoid_tick(&s, 1040));
    TEST_ASSERT_EQUAL_UINT8(0, solenoid_tick(&s, 9999));
}

void test_tick_after_retrigger_extends_window(void) {
    solenoid_t s;
    make_default(&s);
    solenoid_note_on(&s, 60, 64, 1000);
    solenoid_note_on(&s, 60, 64, 1030);
    TEST_ASSERT_EQUAL_UINT8(130, solenoid_tick(&s, 1060));
    TEST_ASSERT_EQUAL_UINT8(0, solenoid_tick(&s, 1070));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_init_sets_defaults);
    RUN_TEST(test_duty_at_velocity_1);
    RUN_TEST(test_duty_at_velocity_127);
    RUN_TEST(test_duty_at_velocity_64);
    RUN_TEST(test_duty_velocity_0_is_zero);
    RUN_TEST(test_duty_velocity_over_127_clamps);
    RUN_TEST(test_duty_monotonic);
    RUN_TEST(test_note_on_matching_note_strikes);
    RUN_TEST(test_note_on_non_matching_note_ignored);
    RUN_TEST(test_note_off_ignored);
    RUN_TEST(test_retrigger_restarts_hold_window);
    RUN_TEST(test_tick_idle_returns_zero);
    RUN_TEST(test_tick_within_window_returns_duty);
    RUN_TEST(test_tick_after_window_closes_returns_zero);
    RUN_TEST(test_tick_after_retrigger_extends_window);
    return UNITY_END();
}
