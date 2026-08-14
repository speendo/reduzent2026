#include <unity.h>
#include "text_parser.h"

void setUp(void) {}
void tearDown(void) {}

void test_note_on(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("n 0 60 100\n", &f));
    TEST_ASSERT_EQUAL_UINT8(0, f.channel);
    TEST_ASSERT_EQUAL_UINT8(EVENT_NOTE, f.type);
    TEST_ASSERT_EQUAL_UINT8(60, f.note);
    TEST_ASSERT_EQUAL_UINT8(100, f.value);
    TEST_ASSERT_EQUAL_UINT8(0, f.value_hi);
}

void test_note_off(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("x 2 61\n", &f));
    TEST_ASSERT_EQUAL_UINT8(2, f.channel);
    TEST_ASSERT_EQUAL_UINT8(EVENT_NOTE, f.type);
    TEST_ASSERT_EQUAL_UINT8(61, f.note);
    TEST_ASSERT_EQUAL_UINT8(0, f.value);
}

void test_panic(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("panic\n", &f));
    TEST_ASSERT_EQUAL_UINT8(ESP_NOW_CHANNEL_BROADCAST, f.channel);
    TEST_ASSERT_EQUAL_UINT8(EVENT_PANIC, f.type);
}

void test_settings(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("settings\n", &f));
    TEST_ASSERT_EQUAL_UINT8(ESP_NOW_CHANNEL_BROADCAST, f.channel);
    TEST_ASSERT_EQUAL_UINT8(EVENT_ENTER_SETTINGS, f.type);
    TEST_ASSERT_EQUAL_UINT8(0xFF, f.note); // all leaves
}

void test_settings_target(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("settings 5\n", &f));
    TEST_ASSERT_EQUAL_UINT8(ESP_NOW_CHANNEL_BROADCAST, f.channel);
    TEST_ASSERT_EQUAL_UINT8(EVENT_ENTER_SETTINGS, f.type);
    TEST_ASSERT_EQUAL_UINT8(5, f.note);
}

void test_pitch_bend(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("p 1 8192\n", &f));
    TEST_ASSERT_EQUAL_UINT8(1, f.channel);
    TEST_ASSERT_EQUAL_UINT8(EVENT_PITCH_BEND, f.type);
    TEST_ASSERT_EQUAL_UINT8(0, f.value);      // 8192 & 0x7F
    TEST_ASSERT_EQUAL_UINT8(64, f.value_hi);  // 8192 >> 7
}

void test_pitch_bend_extremes(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("p 0 0\n", &f));
    TEST_ASSERT_EQUAL_UINT8(0, f.value);
    TEST_ASSERT_EQUAL_UINT8(0, f.value_hi);
    TEST_ASSERT_EQUAL(1, parse_command("p 0 16383\n", &f));
    TEST_ASSERT_EQUAL_UINT8(127, f.value);
    TEST_ASSERT_EQUAL_UINT8(127, f.value_hi);
}

void test_channel_aftertouch(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("a 2 77\n", &f));
    TEST_ASSERT_EQUAL_UINT8(2, f.channel);
    TEST_ASSERT_EQUAL_UINT8(EVENT_CHANNEL_AFTERTOUCH, f.type);
    TEST_ASSERT_EQUAL_UINT8(77, f.value);
}

void test_poly_aftertouch(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("pa 3 64 88\n", &f));
    TEST_ASSERT_EQUAL_UINT8(3, f.channel);
    TEST_ASSERT_EQUAL_UINT8(EVENT_POLY_AFTERTOUCH, f.type);
    TEST_ASSERT_EQUAL_UINT8(64, f.note);
    TEST_ASSERT_EQUAL_UINT8(88, f.value);
}

void test_program_change(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("g 4 9\n", &f));
    TEST_ASSERT_EQUAL_UINT8(4, f.channel);
    TEST_ASSERT_EQUAL_UINT8(EVENT_PROGRAM_CHANGE, f.type);
    TEST_ASSERT_EQUAL_UINT8(9, f.value);
}

void test_vibrato(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("v 5 50\n", &f));
    TEST_ASSERT_EQUAL_UINT8(5, f.channel);
    TEST_ASSERT_EQUAL_UINT8(EVENT_CC1_VIBRATO, f.type);
    TEST_ASSERT_EQUAL_UINT8(50, f.value);
}

void test_p_vs_pa_vs_panic(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(1, parse_command("pa 0 60 100\n", &f));
    TEST_ASSERT_EQUAL_UINT8(EVENT_POLY_AFTERTOUCH, f.type);
    TEST_ASSERT_EQUAL(1, parse_command("p 0 1000\n", &f));
    TEST_ASSERT_EQUAL_UINT8(EVENT_PITCH_BEND, f.type);
    TEST_ASSERT_EQUAL(1, parse_command("panic\n", &f));
    TEST_ASSERT_EQUAL_UINT8(EVENT_PANIC, f.type);
}

void test_rejects(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(0, parse_command("", &f));
    TEST_ASSERT_EQUAL(0, parse_command("\n", &f));
    TEST_ASSERT_EQUAL(0, parse_command("garbage", &f));
    TEST_ASSERT_EQUAL(0, parse_command("n 99 60 100\n", &f));  // channel out of range
    TEST_ASSERT_EQUAL(0, parse_command("n 0 200 100\n", &f));  // note out of range
    TEST_ASSERT_EQUAL(0, parse_command("n 0 60 200\n", &f));   // vel out of range
    TEST_ASSERT_EQUAL(0, parse_command("n 0 60\n", &f));       // missing arg
    TEST_ASSERT_EQUAL(0, parse_command("p 99 0\n", &f));       // channel out of range
    TEST_ASSERT_EQUAL(0, parse_command("p 0 20000\n", &f));    // bend out of range
    TEST_ASSERT_EQUAL(0, parse_command("p 0\n", &f));          // missing arg
    TEST_ASSERT_EQUAL(0, parse_command("a 0 200\n", &f));      // pressure out of range
    TEST_ASSERT_EQUAL(0, parse_command("pa 0 200 100\n", &f)); // note out of range
    TEST_ASSERT_EQUAL(0, parse_command("g 0 200\n", &f));      // program out of range
    TEST_ASSERT_EQUAL(0, parse_command("v 0 200\n", &f));      // depth out of range
    TEST_ASSERT_EQUAL(0, parse_command("s\n", &f));           // incomplete settings
    TEST_ASSERT_EQUAL(0, parse_command("settings 255\n", &f)); // id out of range (0xFF reserved)
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_note_on);
    RUN_TEST(test_note_off);
    RUN_TEST(test_panic);
    RUN_TEST(test_settings);
    RUN_TEST(test_settings_target);
    RUN_TEST(test_pitch_bend);
    RUN_TEST(test_pitch_bend_extremes);
    RUN_TEST(test_channel_aftertouch);
    RUN_TEST(test_poly_aftertouch);
    RUN_TEST(test_program_change);
    RUN_TEST(test_vibrato);
    RUN_TEST(test_p_vs_pa_vs_panic);
    RUN_TEST(test_rejects);
    return UNITY_END();
}
