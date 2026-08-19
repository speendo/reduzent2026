#include <unity.h>
#include "mode.h"

void setUp(void) {}
void tearDown(void) {}

void test_init_live(void) {
    mode_state_t s;
    mode_init(&s, 30000);
    TEST_ASSERT_EQUAL(MODE_LIVE, s.mode);
    TEST_ASSERT_EQUAL(30000, s.settings_window_ms);
    TEST_ASSERT_FALSE(mode_is_settings(&s));
}

void test_boot_window_zero_stays_live(void) {
    mode_state_t s;
    mode_init(&s, 0);
    TEST_ASSERT_FALSE(mode_boot(&s, 1000));
    TEST_ASSERT_EQUAL(MODE_LIVE, s.mode);
}

void test_boot_window_positive_enters_settings(void) {
    mode_state_t s;
    mode_init(&s, 30000);
    TEST_ASSERT_TRUE(mode_boot(&s, 1000));
    TEST_ASSERT_EQUAL(MODE_SETTINGS, s.mode);
    TEST_ASSERT_EQUAL(1000, s.settings_start_ms);
}

void test_enter_exit_settings(void) {
    mode_state_t s;
    mode_init(&s, 30000);
    mode_enter_settings(&s, 500);
    TEST_ASSERT_TRUE(mode_is_settings(&s));
    TEST_ASSERT_EQUAL(500, s.settings_start_ms);
    mode_exit_settings(&s);
    TEST_ASSERT_FALSE(mode_is_settings(&s));
}

void test_tick_before_timeout_stays_settings(void) {
    mode_state_t s;
    mode_init(&s, 30000);
    mode_enter_settings(&s, 1000);
    TEST_ASSERT_FALSE(mode_tick(&s, 1000 + 29999));
    TEST_ASSERT_TRUE(mode_is_settings(&s));
}

void test_tick_at_timeout_exits_to_live(void) {
    mode_state_t s;
    mode_init(&s, 30000);
    mode_enter_settings(&s, 1000);
    TEST_ASSERT_TRUE(mode_tick(&s, 1000 + 30000));
    TEST_ASSERT_FALSE(mode_is_settings(&s));
}

void test_tick_zero_window_exits_immediately(void) {
    mode_state_t s;
    mode_init(&s, 0);
    mode_enter_settings(&s, 1000);
    TEST_ASSERT_TRUE(mode_tick(&s, 1000));
    TEST_ASSERT_FALSE(mode_is_settings(&s));
}

void test_tick_after_millis_wraparound(void) {
    // settings_start_ms set 31000 ms in the past in uint32 space, spanning the
    // 2^32 millis() wraparound; the 30000 ms window must still expire.
    mode_state_t s;
    mode_init(&s, 30000);
    mode_enter_settings(&s, (uint32_t)(0xFFFFFFFFu - 31000u));
    TEST_ASSERT_TRUE(mode_tick(&s, (uint32_t)1000));
    TEST_ASSERT_FALSE(mode_is_settings(&s));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_init_live);
    RUN_TEST(test_boot_window_zero_stays_live);
    RUN_TEST(test_boot_window_positive_enters_settings);
    RUN_TEST(test_enter_exit_settings);
    RUN_TEST(test_tick_before_timeout_stays_settings);
    RUN_TEST(test_tick_at_timeout_exits_to_live);
    RUN_TEST(test_tick_zero_window_exits_immediately);
    RUN_TEST(test_tick_after_millis_wraparound);
    return UNITY_END();
}
