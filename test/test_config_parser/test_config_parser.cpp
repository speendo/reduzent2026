#include <unity.h>
#include "config_parser.h"

void setUp(void) {}
void tearDown(void) {}

void test_cfgget(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    char out[128];
    TEST_ASSERT_EQUAL(CFG_GET, config_handle_line("cfgget\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_STRING("espnow_channel=13\nsettings_window_sec=30\n", out);
}

void test_cfgset_espnow_channel(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    char out[128];
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset espnow_channel 7\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_UINT8(7, cfg.espnow_channel);
    TEST_ASSERT_EQUAL_STRING("espnow_channel=7\n", out);
}

void test_cfgset_window(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    char out[128];
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset settings_window_sec 120\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_UINT16(120, cfg.settings_window_sec);
    TEST_ASSERT_EQUAL_STRING("settings_window_sec=120\n", out);
}

void test_cfgset_boundaries(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    char out[128];
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset espnow_channel 1\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_UINT8(1, cfg.espnow_channel);
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset espnow_channel 14\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_UINT8(14, cfg.espnow_channel);
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset settings_window_sec 0\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_UINT16(0, cfg.settings_window_sec);
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset settings_window_sec 300\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_UINT16(300, cfg.settings_window_sec);
}

void test_cfgset_out_of_range(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    char out[128];
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset espnow_channel 15\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_UINT8(13, cfg.espnow_channel);  // unchanged
    TEST_ASSERT_EQUAL_STRING("error: value out of range\n", out);
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset espnow_channel 0\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_UINT8(13, cfg.espnow_channel);
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset settings_window_sec 301\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_UINT16(30, cfg.settings_window_sec);
}

void test_cfgset_unknown_key(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    char out[128];
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset bogus 5\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_STRING("error: unknown key\n", out);
}

void test_cfgset_missing_arg(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    char out[128];
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_STRING("error: missing argument\n", out);
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset espnow_channel\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_STRING("error: missing argument\n", out);
}

void test_cfgsave(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    char out[128];
    TEST_ASSERT_EQUAL(CFG_SAVE, config_handle_line("cfgsave\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_STRING("saved\n", out);
}

void test_cfgreset(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    char out[128];
    TEST_ASSERT_EQUAL(CFG_SET, config_handle_line("cfgset espnow_channel 7\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL(CFG_RESET, config_handle_line("cfgreset\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL_UINT8(13, cfg.espnow_channel);
    TEST_ASSERT_EQUAL_UINT16(30, cfg.settings_window_sec);
    TEST_ASSERT_EQUAL_STRING("espnow_channel=13\nsettings_window_sec=30\n", out);
}

void test_non_cfg_line(void) {
    controller_config_t cfg;
    config_defaults(&cfg);
    char out[128];
    TEST_ASSERT_EQUAL(CFG_NONE, config_handle_line("n 0 60 100\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL(CFG_NONE, config_handle_line("garbage\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL(CFG_NONE, config_handle_line("cfggetfoo\n", &cfg, out, sizeof(out)));
    TEST_ASSERT_EQUAL(CFG_NONE, config_handle_line("cfgsetfoo 1\n", &cfg, out, sizeof(out)));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_cfgget);
    RUN_TEST(test_cfgset_espnow_channel);
    RUN_TEST(test_cfgset_window);
    RUN_TEST(test_cfgset_boundaries);
    RUN_TEST(test_cfgset_out_of_range);
    RUN_TEST(test_cfgset_unknown_key);
    RUN_TEST(test_cfgset_missing_arg);
    RUN_TEST(test_cfgsave);
    RUN_TEST(test_cfgreset);
    RUN_TEST(test_non_cfg_line);
    return UNITY_END();
}
