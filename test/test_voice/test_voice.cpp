#include <unity.h>
#include "voice.h"

void setUp(void) {}
void tearDown(void) {}

// Instant attack so voices reach full level on the first tick.
static const envelope_params_t FAST = { 0, 1000, 1000, 100 };

static void init(voice_table_t* vt) { voice_table_init(vt, &FAST); }

void test_init_all_free(void) {
    voice_table_t vt;
    init(&vt);
    TEST_ASSERT_EQUAL_UINT8(0, voice_active_count(&vt));
}

void test_note_on_claims_free_voice(void) {
    voice_table_t vt;
    init(&vt);
    int idx = voice_note_on(&vt, 60, 100, 0);
    TEST_ASSERT_EQUAL(0, idx);
    TEST_ASSERT_EQUAL_UINT8(60, vt.voices[0].note);
    TEST_ASSERT_EQUAL(ENV_STAGE_ATTACK, vt.voices[0].stage);
    TEST_ASSERT_EQUAL_UINT32(0, vt.voices[0].phase);
    TEST_ASSERT_EQUAL_UINT8(1, voice_active_count(&vt));
}

void test_note_on_zero_velocity_rejected(void) {
    voice_table_t vt;
    init(&vt);
    TEST_ASSERT_EQUAL(-1, voice_note_on(&vt, 60, 0, 0));
    TEST_ASSERT_EQUAL_UINT8(0, voice_active_count(&vt));
}

void test_note_off_sets_release(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 0);
    voice_tick(&vt, 0); // attack 0 -> decay, level 100
    TEST_ASSERT_EQUAL(1, voice_note_off(&vt, 60, 0));
    TEST_ASSERT_EQUAL(ENV_STAGE_RELEASE, vt.voices[0].stage);
    TEST_ASSERT_EQUAL_UINT16(100, vt.voices[0].release_start);
}

void test_note_off_unknown_returns_zero(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 0);
    TEST_ASSERT_EQUAL(0, voice_note_off(&vt, 99, 0));
}

void test_retrigger_reuses_voice(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 0);
    voice_note_off(&vt, 60, 0);
    int idx = voice_note_on(&vt, 60, 100, 100);
    TEST_ASSERT_EQUAL(0, idx); // same slot, not a new voice
    TEST_ASSERT_EQUAL(ENV_STAGE_ATTACK, vt.voices[0].stage);
    TEST_ASSERT_EQUAL_UINT8(1, voice_active_count(&vt));
}

void test_steal_quietest(void) {
    voice_table_t vt;
    init(&vt);
    for (int i = 0; i < MAX_VOICES; i++) voice_note_on(&vt, (uint8_t)(60 + i), 100, 0);
    voice_tick(&vt, 0);      // all at level 100
    vt.voices[5].level = 10; // make voice 5 the quietest
    int idx = voice_note_on(&vt, 80, 100, 1000);
    TEST_ASSERT_EQUAL(5, idx);
    TEST_ASSERT_EQUAL_UINT8(80, vt.voices[5].note);
}

void test_steal_oldest_tiebreak(void) {
    voice_table_t vt;
    init(&vt);
    for (int i = 0; i < MAX_VOICES; i++) {
        voice_note_on(&vt, (uint8_t)(60 + i), 100, (uint32_t)(100 * i));
    }
    voice_tick(&vt, 0);
    for (int i = 0; i < MAX_VOICES; i++) vt.voices[i].level = 50; // equal levels
    int idx = voice_note_on(&vt, 80, 100, 5000);
    TEST_ASSERT_EQUAL(0, idx); // voice 0 has oldest born_ms
}

void test_tick_frees_released_voice(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 0);
    voice_tick(&vt, 0);         // -> level 100
    voice_note_off(&vt, 60, 0); // release_start 100, release 1000ms
    voice_tick(&vt, 100);
    TEST_ASSERT_EQUAL(ENV_STAGE_RELEASE, vt.voices[0].stage);
    voice_tick(&vt, 1100);      // elapsed >= 1000 -> idle
    TEST_ASSERT_EQUAL(ENV_STAGE_IDLE, vt.voices[0].stage);
    TEST_ASSERT_EQUAL_UINT8(VOICE_FREE_NOTE, vt.voices[0].note);
    TEST_ASSERT_EQUAL_UINT8(0, voice_active_count(&vt));
}

void test_arpeggio_step(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 0);
    voice_note_on(&vt, 64, 100, 0);
    voice_note_on(&vt, 67, 100, 0);
    TEST_ASSERT_EQUAL(0, voice_arpeggio_step(&vt, -1));
    TEST_ASSERT_EQUAL(1, voice_arpeggio_step(&vt, 0));
    TEST_ASSERT_EQUAL(2, voice_arpeggio_step(&vt, 1));
    TEST_ASSERT_EQUAL(0, voice_arpeggio_step(&vt, 2));
}

void test_arpeggio_step_empty(void) {
    voice_table_t vt;
    init(&vt);
    TEST_ASSERT_EQUAL(-1, voice_arpeggio_step(&vt, -1));
}

void test_active_count(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 0);
    voice_note_on(&vt, 64, 100, 0);
    voice_note_on(&vt, 67, 100, 0);
    TEST_ASSERT_EQUAL_UINT8(3, voice_active_count(&vt));
}

// --- monophonic selector (voice_mono_current) tests ---

// Put a voice into a deterministic "held" state without envelope timing.
static void set_held(voice_t* v, uint8_t note, uint32_t born) {
    v->note = note;
    v->velocity = 100;
    v->stage = ENV_STAGE_SUSTAIN;
    v->level = 100;
    v->release_start = 0;
    v->phase = 0;
    v->stage_start_ms = 0;
    v->born_ms = born;
}

void test_mono_current_empty(void) {
    voice_table_t vt;
    init(&vt);
    TEST_ASSERT_EQUAL(-1, voice_mono_current(&vt));
}

void test_mono_current_single_held(void) {
    voice_table_t vt;
    init(&vt);
    set_held(&vt.voices[0], 60, 100);
    TEST_ASSERT_EQUAL(0, voice_mono_current(&vt));
}

void test_mono_current_last_pressed_wins(void) {
    voice_table_t vt;
    init(&vt);
    set_held(&vt.voices[0], 60, 100);
    set_held(&vt.voices[1], 64, 200);
    TEST_ASSERT_EQUAL(1, voice_mono_current(&vt));
}

void test_mono_current_falls_back_on_release(void) {
    voice_table_t vt;
    init(&vt);
    set_held(&vt.voices[0], 60, 100);
    set_held(&vt.voices[1], 64, 200);
    vt.voices[1].stage = ENV_STAGE_RELEASE; // top note released
    TEST_ASSERT_EQUAL(0, voice_mono_current(&vt)); // falls back to held v0
}

void test_mono_current_release_tail(void) {
    voice_table_t vt;
    init(&vt);
    set_held(&vt.voices[0], 60, 100);
    vt.voices[0].stage = ENV_STAGE_RELEASE; // nothing held, one releasing
    TEST_ASSERT_EQUAL(0, voice_mono_current(&vt)); // release tail still selected
}

void test_mono_current_all_idle(void) {
    voice_table_t vt;
    init(&vt);
    set_held(&vt.voices[0], 60, 100);
    vt.voices[0].stage = ENV_STAGE_IDLE;
    TEST_ASSERT_EQUAL(-1, voice_mono_current(&vt));
}

void test_note_on_sets_hold_refresh(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 500);
    TEST_ASSERT_EQUAL_UINT32(500, vt.voices[0].hold_refresh_ms);
}

void test_note_hold_refreshes_active(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 0);
    int idx = voice_note_hold(&vt, 60, 100, 1000);
    TEST_ASSERT_EQUAL(0, idx);
    TEST_ASSERT_EQUAL_UINT32(1000, vt.voices[0].hold_refresh_ms);
    TEST_ASSERT_EQUAL(ENV_STAGE_ATTACK, vt.voices[0].stage); // refreshed, not re-attacked
}

void test_note_hold_starts_missing(void) {
    voice_table_t vt;
    init(&vt);
    int idx = voice_note_hold(&vt, 60, 100, 1000);
    TEST_ASSERT_EQUAL(0, idx);
    TEST_ASSERT_EQUAL_UINT8(60, vt.voices[0].note);
    TEST_ASSERT_EQUAL_UINT8(1, voice_active_count(&vt));
}

void test_watchdog_releases_stuck_sustain(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 0);
    voice_tick(&vt, 0);     // attack 0 -> decay
    voice_tick(&vt, 1000);  // decay 1000 -> sustain
    TEST_ASSERT_EQUAL(ENV_STAGE_SUSTAIN, vt.voices[0].stage);
    voice_watchdog(&vt, 0, 3000);    // 0ms elapsed < 3000
    TEST_ASSERT_EQUAL(ENV_STAGE_SUSTAIN, vt.voices[0].stage);
    voice_watchdog(&vt, 3000, 3000); // 3000ms elapsed >= 3000
    TEST_ASSERT_EQUAL(ENV_STAGE_RELEASE, vt.voices[0].stage);
}

void test_watchdog_refresh_prevents_release(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 0);
    voice_tick(&vt, 0);
    voice_tick(&vt, 1000);
    voice_note_hold(&vt, 60, 100, 2500);
    voice_watchdog(&vt, 3000, 3000); // 3000 - 2500 = 500 < 3000
    TEST_ASSERT_EQUAL(ENV_STAGE_SUSTAIN, vt.voices[0].stage);
    voice_watchdog(&vt, 5500, 3000); // 5500 - 2500 = 3000 >= 3000
    TEST_ASSERT_EQUAL(ENV_STAGE_RELEASE, vt.voices[0].stage);
}

void test_steal_sets_hold_refresh_for_watchdog(void) {
    voice_table_t vt;
    init(&vt);
    for (int i = 0; i < MAX_VOICES; i++) voice_note_on(&vt, (uint8_t)(60 + i), 100, 0);
    voice_tick(&vt, 0);     // attack 0 -> decay
    voice_tick(&vt, 1000);  // decay 1000 -> sustain
    int idx = voice_note_on(&vt, 80, 100, 5000); // all 8 busy -> steal one
    TEST_ASSERT_EQUAL_UINT32(5000, vt.voices[idx].hold_refresh_ms);
    voice_tick(&vt, 5000);  // stolen voice: attack 0 -> decay
    voice_tick(&vt, 6000);  // stolen voice: decay 1000 -> sustain
    TEST_ASSERT_EQUAL(ENV_STAGE_SUSTAIN, vt.voices[idx].stage);
    voice_watchdog(&vt, 6000, 3000); // 6000-5000 = 1000 < 3000: must NOT release
    TEST_ASSERT_EQUAL(ENV_STAGE_SUSTAIN, vt.voices[idx].stage);
    voice_watchdog(&vt, 8000, 3000); // 8000-5000 = 3000 >= 3000: now release
    TEST_ASSERT_EQUAL(ENV_STAGE_RELEASE, vt.voices[idx].stage);
}

void test_all_notes_off_releases_all(void) {
    voice_table_t vt;
    init(&vt);
    voice_note_on(&vt, 60, 100, 0);
    voice_note_on(&vt, 64, 100, 0);
    voice_note_on(&vt, 67, 100, 0);
    voice_tick(&vt, 0);
    voice_all_notes_off(&vt, 1000);
    for (int i = 0; i < 3; i++) TEST_ASSERT_EQUAL(ENV_STAGE_RELEASE, vt.voices[i].stage);
    TEST_ASSERT_EQUAL_UINT8(3, voice_active_count(&vt)); // still active while releasing
}

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_init_all_free);
    RUN_TEST(test_note_on_claims_free_voice);
    RUN_TEST(test_note_on_zero_velocity_rejected);
    RUN_TEST(test_note_off_sets_release);
    RUN_TEST(test_note_off_unknown_returns_zero);
    RUN_TEST(test_retrigger_reuses_voice);
    RUN_TEST(test_steal_quietest);
    RUN_TEST(test_steal_oldest_tiebreak);
    RUN_TEST(test_tick_frees_released_voice);
    RUN_TEST(test_arpeggio_step);
    RUN_TEST(test_arpeggio_step_empty);
    RUN_TEST(test_active_count);
    RUN_TEST(test_mono_current_empty);
    RUN_TEST(test_mono_current_single_held);
    RUN_TEST(test_mono_current_last_pressed_wins);
    RUN_TEST(test_mono_current_falls_back_on_release);
    RUN_TEST(test_mono_current_release_tail);
    RUN_TEST(test_mono_current_all_idle);
    RUN_TEST(test_note_on_sets_hold_refresh);
    RUN_TEST(test_note_hold_refreshes_active);
    RUN_TEST(test_note_hold_starts_missing);
    RUN_TEST(test_watchdog_releases_stuck_sustain);
    RUN_TEST(test_watchdog_refresh_prevents_release);
    RUN_TEST(test_steal_sets_hold_refresh_for_watchdog);
    RUN_TEST(test_all_notes_off_releases_all);
    return UNITY_END();
}
