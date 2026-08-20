#include <unity.h>
#include <string.h>
#include "config.h"
#include "config_parser.h"

/* Test the save validation path.  In the parasol UI:
   - Fields with unsaved changes are "dirty"
   - Clicking Save sends an S command with all field values
   - The firmware calls config_validate_field() on each; if valid → save
     succeeds → return ESP_OK → parasol hides the Save button
   - If any value fails validation → save fails → return ESP_FAIL
     → Save button stays visible.
   This test exercises config_validate_field() directly since it's the
   shared validation logic used by both the serial cfg-save and the
   parasol WebS save callback.                                      */

void setUp(void) {}
void tearDown(void) {}

void test_leaf_valid_field_values_allow_save(void) {
    /* All valid leaf fields → save would succeed (ESP_OK) → save button hides.
       config_validate_field() returns 0 for valid fields.               */
    TEST_ASSERT_EQUAL(0,  config_validate_field("espnow_channel", "13"));
    TEST_ASSERT_EQUAL(0,  config_validate_field("node_id", "0"));
    TEST_ASSERT_EQUAL(0,  config_validate_field("gpio_piezo", "5"));
    TEST_ASSERT_EQUAL(0,  config_validate_field("gpio_solenoid", "6"));
    TEST_ASSERT_EQUAL(0,  config_validate_field("solenoid_note", "36"));
    TEST_ASSERT_EQUAL(0,  config_validate_field("solenoid_hold_ms", "40"));
    TEST_ASSERT_EQUAL(0,  config_validate_field("solenoid_duty_min", "40"));
    TEST_ASSERT_EQUAL(0,  config_validate_field("solenoid_duty_max", "220"));
    TEST_ASSERT_EQUAL(0,  config_validate_field("piezo_adsr_attack_ms", "5"));
    TEST_ASSERT_EQUAL(0,  config_validate_field("piezo_adsr_decay_ms", "100"));
    TEST_ASSERT_EQUAL(0,  config_validate_field("piezo_adsr_release_ms", "100"));
}

void test_leaf_invalid_channel_blocks_save_and_hides_button(void) {
    /* espnow_channel 0 or 15 is invalid → save fails (ESP_FAIL)
       → Save button stays visible.                                    */
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("espnow_channel", "0"));
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("espnow_channel", "15"));
}

void test_leaf_unassigned_node_id_blocks_save(void) {
    /* node_id 255 is "unassigned" — not a valid GPIO/settings value.
       Save should fail to prevent configuring an unassigned leaf.     */
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("node_id", "255"));
}

void test_leaf_gpio_boundary_values(void) {
    /* Valid GPIO range is 0-28. */
    TEST_ASSERT_EQUAL(0, config_validate_field("gpio_piezo", "0"));
    TEST_ASSERT_EQUAL(0, config_validate_field("gpio_piezo", "28"));
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("gpio_piezo", "29"));
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("gpio_solenoid", "29"));
}

void test_leaf_solenoid_hold_ms_boundary(void) {
    /* solenoid_hold_ms 9 and 501 are invalid. */
    TEST_ASSERT_EQUAL(0, config_validate_field("solenoid_hold_ms", "10"));
    TEST_ASSERT_EQUAL(0, config_validate_field("solenoid_hold_ms", "500"));
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("solenoid_hold_ms", "9"));
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("solenoid_hold_ms", "501"));
}

void test_controller_valid_values_allow_save(void) {
    TEST_ASSERT_EQUAL(0, config_validate_field("espnow_channel", "13"));
    TEST_ASSERT_EQUAL(0, config_validate_field("settings_window_sec", "0"));
    TEST_ASSERT_EQUAL(0, config_validate_field("settings_window_sec", "300"));
}

void test_controller_out_of_range_blocks_save(void) {
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("espnow_channel", "15"));
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("settings_window_sec", "301"));
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("espnow_channel", "0"));
}

void test_controller_unknown_key_blocks_save(void) {
    /* Unknown keys must fail validation — prevents silent accept of
       spurious field values from a corrupted WS payload.             */
    TEST_ASSERT_NOT_EQUAL(0, config_validate_field("bogus_field", "42"));
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_leaf_valid_field_values_allow_save);
    RUN_TEST(test_leaf_invalid_channel_blocks_save_and_hides_button);
    RUN_TEST(test_leaf_unassigned_node_id_blocks_save);
    RUN_TEST(test_leaf_gpio_boundary_values);
    RUN_TEST(test_leaf_solenoid_hold_ms_boundary);
    RUN_TEST(test_controller_valid_values_allow_save);
    RUN_TEST(test_controller_out_of_range_blocks_save);
    RUN_TEST(test_controller_unknown_key_blocks_save);
    return UNITY_END();
}