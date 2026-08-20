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

// --- Client-aware timeout pausing ---

void test_client_connect_pauses_timeout(void) {
    mode_state_t s;
    mode_init(&s, 30000);
    mode_enter_settings(&s, 1000);

    // After 20 s with no clients, timer should still be running
    TEST_ASSERT_FALSE(mode_tick(&s, 21000));

    // Client connects at 20 s — timer pauses
    mode_set_clients(&s, 1, 20000);

    // 10 s later (30 s total) — still in settings because timeout paused
    TEST_ASSERT_FALSE(mode_tick(&s, 30000));

    // 50 s later (70 s total) — still paused
    TEST_ASSERT_FALSE(mode_tick(&s, 70000));

    // Client disconnects — grace starts at 70 s
    mode_set_clients(&s, 0, 70000);

    // Grace hasn't expired yet
    TEST_ASSERT_FALSE(mode_tick(&s, 76000));

    // Grace expires at 77 s — exit
    TEST_ASSERT_TRUE(mode_tick(&s, 77001));
    TEST_ASSERT_FALSE(mode_is_settings(&s));
}

void test_disconnect_starts_grace(void) {
    mode_state_t s;
    mode_init(&s, 30000);
    mode_enter_settings(&s, 1000);

    // Client connects and stays
    mode_set_clients(&s, 1, 1000);
    mode_set_clients(&s, 1, 20000);

    // Disconnect at 20 s — grace starts
    mode_set_clients(&s, 0, 20000);

    // Still in grace after 6 s
    TEST_ASSERT_FALSE(mode_tick(&s, 26000));

    // Grace expires after 7 s — exit
    TEST_ASSERT_TRUE(mode_tick(&s, 27001));
    TEST_ASSERT_FALSE(mode_is_settings(&s));
}

void test_reconnect_during_grace_cancels_it(void) {
    mode_state_t s;
    mode_init(&s, 30000);
    mode_enter_settings(&s, 1000);

    // Connect then disconnect — grace starts
    mode_set_clients(&s, 1, 1000);
    mode_set_clients(&s, 0, 5000);

    // 6 s later — in grace
    TEST_ASSERT_FALSE(mode_tick(&s, 11000));

    // Client reconnects — cancel grace
    mode_set_clients(&s, 1, 11000);

    // 10 s later — still in settings (timer paused, no grace)
    TEST_ASSERT_FALSE(mode_tick(&s, 21000));

    // Disconnect again — new grace period starts
    mode_set_clients(&s, 0, 21000);

    // 7 s later — exit
    TEST_ASSERT_TRUE(mode_tick(&s, 28001));
    TEST_ASSERT_FALSE(mode_is_settings(&s));
}

void test_exit_request(void) {
    mode_state_t s;
    mode_init(&s, 30000);
    mode_enter_settings(&s, 1000);

    // Connect a client to pause timer
    mode_set_clients(&s, 1, 5000);

    // Request exit — should work even with client connected
    mode_request_exit(&s);
    TEST_ASSERT_TRUE(mode_tick(&s, 6000));
    TEST_ASSERT_FALSE(mode_is_settings(&s));
}

void test_exit_request_clears_grace(void) {
    mode_state_t s;
    mode_init(&s, 30000);
    mode_enter_settings(&s, 1000);

    // Disconnect starts grace
    mode_set_clients(&s, 1, 1000);
    mode_set_clients(&s, 0, 5000);

    // Request exit during grace
    mode_request_exit(&s);
    TEST_ASSERT_TRUE(mode_tick(&s, 6000));
    TEST_ASSERT_FALSE(mode_is_settings(&s));

    // Verify grace is cleared (re-entering settings should start fresh)
    mode_enter_settings(&s, 10000);
    TEST_ASSERT_EQUAL(0, s.grace_start_ms);
}

void test_set_clients_ignores_in_live_mode(void) {
    mode_state_t s;
    mode_init(&s, 30000);

    // In live mode — set_clients updates count but doesn't affect grace
    mode_set_clients(&s, 1, 1000);
    TEST_ASSERT_EQUAL(1, s.client_count);
    TEST_ASSERT_EQUAL(0, s.grace_start_ms);

    // Entering settings inherits the client count (realistic: AP is up)
    mode_enter_settings(&s, 2000);
    // Timer should be paused because client_count > 0
    TEST_ASSERT_FALSE(mode_tick(&s, 50000));

    // Disconnect — grace starts
    mode_set_clients(&s, 0, 50000);
    TEST_ASSERT_TRUE(mode_tick(&s, 50000 + MODE_GRACE_MS + 1));
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
    RUN_TEST(test_client_connect_pauses_timeout);
    RUN_TEST(test_disconnect_starts_grace);
    RUN_TEST(test_reconnect_during_grace_cancels_it);
    RUN_TEST(test_exit_request);
    RUN_TEST(test_exit_request_clears_grace);
    RUN_TEST(test_set_clients_ignores_in_live_mode);
    return UNITY_END();
}
