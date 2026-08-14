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

void test_rejects(void) {
    espnow_frame_t f;
    TEST_ASSERT_EQUAL(0, parse_command("", &f));
    TEST_ASSERT_EQUAL(0, parse_command("\n", &f));
    TEST_ASSERT_EQUAL(0, parse_command("garbage", &f));
    TEST_ASSERT_EQUAL(0, parse_command("n 99 60 100\n", &f)); // channel out of range
    TEST_ASSERT_EQUAL(0, parse_command("n 0 200 100\n", &f)); // note out of range
    TEST_ASSERT_EQUAL(0, parse_command("n 0 60 200\n", &f));  // vel out of range
    TEST_ASSERT_EQUAL(0, parse_command("n 0 60\n", &f));      // missing arg
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_note_on);
    RUN_TEST(test_note_off);
    RUN_TEST(test_panic);
    RUN_TEST(test_rejects);
    return UNITY_END();
}
