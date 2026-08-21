#!/usr/bin/env python3
"""Unit tests for tools/looper.py — model + save format (slice 2).

Covers the Loop/Track/Event model, the reduzent-loop v1 text serializer
(loop_to_text / loop_from_text), and the save_loop / load_loop file wrappers.
Run:

    python3 tools/test_looper.py
"""

import os
import re
import tempfile
import unittest

from looper import (
    Event,
    Track,
    Loop,
    loop_to_text,
    loop_from_text,
    save_loop,
    load_loop,
    Engine,
    sanitize_name,
    loop_path,
    list_loop_names,
    save_loop_named,
    load_loop_named,
    status_lines,
    _visible_len,
    _truncate_visible,
    parse_channels,
    parse_hotkeys,
    present_channels,
    step_channel,
    edit_target,
    hotkey_action,
    column_lines,
)


class TestModel(unittest.TestCase):
    def test_event_fields(self):
        e = Event(phase=0.5, seq=3, cmd="n 0 60 100")
        self.assertEqual(e.phase, 0.5)
        self.assertEqual(e.seq, 3)
        self.assertEqual(e.cmd, "n 0 60 100")

    def test_track_defaults(self):
        t = Track()
        self.assertEqual(t.events, [])
        self.assertFalse(t.muted)

    def test_loop_defaults(self):
        loop = Loop()
        self.assertEqual(loop.length, 0.0)
        self.assertEqual(loop.tracks, {})
        self.assertIsNone(loop.anchor)


class TestLoopToText(unittest.TestCase):
    def test_empty_loop(self):
        self.assertEqual(
            loop_to_text(Loop()),
            "reduzent-loop v1\nlength 0.000000\n",
        )

    def test_one_track_sorted_by_seq(self):
        loop = Loop(length=4.0)
        loop.tracks[0] = Track(
            events=[
                Event(phase=0.0, seq=0, cmd="n 0 60 100"),
                Event(phase=0.0, seq=1, cmd="v 0 64"),
                Event(phase=0.5, seq=2, cmd="x 0 60"),
            ]
        )
        self.assertEqual(
            loop_to_text(loop),
            "reduzent-loop v1\n"
            "length 4.000000\n"
            "0.000000 n 0 60 100\n"
            "0.000000 v 0 64\n"
            "0.500000 x 0 60\n",
        )

    def test_mute_header_and_cross_track_seq_order(self):
        loop = Loop(length=4.0)
        loop.tracks[0] = Track(events=[Event(phase=1.0, seq=3, cmd="n 0 64 90")])
        loop.tracks[3] = Track(
            events=[
                Event(phase=0.5, seq=1, cmd="x 3 60"),
                Event(phase=1.25, seq=4, cmd="n 3 67 90"),
            ],
            muted=True,
        )
        self.assertEqual(
            loop_to_text(loop),
            "reduzent-loop v1\n"
            "length 4.000000\n"
            "mute 3\n"
            "0.500000 x 3 60\n"
            "1.000000 n 0 64 90\n"
            "1.250000 n 3 67 90\n",
        )


class TestLoopFromText(unittest.TestCase):
    def test_spec_example(self):
        text = (
            "reduzent-loop v1\n"
            "length 4.0\n"
            "mute 3\n"
            "0.000000 n 0 60 100\n"
            "0.000000 v 0 64\n"
            "0.500000 x 0 60\n"
            "1.250000 n 3 67 90\n"
        )
        loop = loop_from_text(text)
        self.assertEqual(loop.length, 4.0)
        self.assertIsNone(loop.anchor)
        self.assertEqual(set(loop.tracks), {0, 3})
        self.assertEqual(
            [(e.phase, e.seq, e.cmd) for e in loop.tracks[0].events],
            [(0.0, 0, "n 0 60 100"), (0.0, 1, "v 0 64"), (0.5, 2, "x 0 60")],
        )
        self.assertFalse(loop.tracks[0].muted)
        self.assertEqual(
            [(e.phase, e.seq, e.cmd) for e in loop.tracks[3].events],
            [(1.25, 3, "n 3 67 90")],
        )
        self.assertTrue(loop.tracks[3].muted)

    def test_unknown_header_lines_ignored(self):
        text = (
            "reduzent-loop v1\n"
            "bpm 120\n"
            "length 4.0\n"
            "some future header\n"
            "0.000000 n 0 60 100\n"
            "\n"
        )
        loop = loop_from_text(text)
        self.assertEqual(loop.length, 4.0)
        self.assertEqual(set(loop.tracks), {0})

    def test_last_length_wins(self):
        text = "reduzent-loop v1\nlength 2.0\nlength 3.5\n0.000000 n 0 60 100\n"
        loop = loop_from_text(text)
        self.assertEqual(loop.length, 3.5)

    def test_mute_channel_without_events_creates_no_track(self):
        text = "reduzent-loop v1\nlength 4.0\nmute 7\n0.000000 n 0 60 100\n"
        loop = loop_from_text(text)
        self.assertEqual(set(loop.tracks), {0})
        self.assertFalse(loop.tracks[0].muted)


class TestMalformed(unittest.TestCase):
    def test_empty_text(self):
        with self.assertRaises(ValueError):
            loop_from_text("")

    def test_wrong_version(self):
        with self.assertRaises(ValueError):
            loop_from_text("reduzent-loop v2\nlength 4.0\n")

    def test_missing_version_header(self):
        with self.assertRaises(ValueError):
            loop_from_text("length 4.0\n")

    def test_missing_length(self):
        with self.assertRaises(ValueError):
            loop_from_text("reduzent-loop v1\n0.000000 n 0 60 100\n")

    def test_length_without_value(self):
        with self.assertRaises(ValueError):
            loop_from_text("reduzent-loop v1\nlength\n")

    def test_bad_length_value(self):
        with self.assertRaises(ValueError):
            loop_from_text("reduzent-loop v1\nlength abc\n")

    def test_mute_with_bad_channel(self):
        with self.assertRaises(ValueError):
            loop_from_text("reduzent-loop v1\nlength 4.0\nmute abc\n")

    def test_bad_phase_value(self):
        with self.assertRaises(ValueError):
            loop_from_text("reduzent-loop v1\nlength 4.0\n0.5.5 n 0 60 100\n")

    def test_command_without_channel(self):
        with self.assertRaises(ValueError):
            loop_from_text("reduzent-loop v1\nlength 4.0\n0.000000 n\n")

    def test_bad_channel_value(self):
        with self.assertRaises(ValueError):
            loop_from_text("reduzent-loop v1\nlength 4.0\n0.000000 n abc 60 100\n")


class TestRoundTrip(unittest.TestCase):
    def test_full_round_trip_equality(self):
        loop = Loop(length=4.0)
        loop.tracks[0] = Track(
            events=[
                Event(phase=0.0, seq=0, cmd="n 0 60 100"),
                Event(phase=0.0, seq=1, cmd="v 0 64"),
                Event(phase=0.5, seq=2, cmd="x 0 60"),
            ]
        )
        loop.tracks[3] = Track(
            events=[Event(phase=1.25, seq=3, cmd="n 3 67 90")], muted=True
        )
        restored = loop_from_text(loop_to_text(loop))
        self.assertEqual(restored, loop)

    def test_seq_reassigned_in_file_order(self):
        loop = Loop(length=4.0)
        loop.tracks[0] = Track(events=[Event(phase=1.0, seq=7, cmd="n 0 64 90")])
        loop.tracks[3] = Track(events=[Event(phase=0.5, seq=3, cmd="x 3 60")])
        restored = loop_from_text(loop_to_text(loop))
        self.assertEqual(
            [(e.seq, e.phase, e.cmd) for e in restored.tracks[0].events],
            [(1, 1.0, "n 0 64 90")],
        )
        self.assertEqual(
            [(e.seq, e.phase, e.cmd) for e in restored.tracks[3].events],
            [(0, 0.5, "x 3 60")],
        )

    def test_empty_state_round_trip(self):
        restored = loop_from_text(loop_to_text(Loop()))
        self.assertEqual(restored.length, 0.0)
        self.assertEqual(restored.tracks, {})
        self.assertIsNone(restored.anchor)

    def test_phases_lossless_to_microsecond(self):
        loop = Loop(length=2.0)
        loop.tracks[0] = Track(events=[Event(phase=0.123456, seq=0, cmd="n 0 60 100")])
        restored = loop_from_text(loop_to_text(loop))
        self.assertEqual(restored.tracks[0].events[0].phase, 0.123456)


class TestSaveLoad(unittest.TestCase):
    def test_save_load_round_trip(self):
        loop = Loop(length=4.0)
        loop.tracks[1] = Track(events=[Event(phase=0.25, seq=0, cmd="n 1 64 100")])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "loop.loop")
            save_loop(path, loop)
            self.assertTrue(os.path.isfile(path))
            restored = load_loop(path)
        self.assertEqual(restored, loop)



class TestEngineFresh(unittest.TestCase):
    def test_phase_none_without_loop(self):
        eng = Engine()
        self.assertIsNone(eng.phase(3.0))
        self.assertFalse(eng.recording)

    def test_fresh_recording_phases_length_anchor(self):
        eng = Engine()
        eng.override_ch = 0
        self.assertEqual(eng.toggle(0.0), [])
        self.assertTrue(eng.recording)
        eng.record("n 0 60 100", 0, 60, 1.0)
        eng.record("x 0 60", 0, 60, 1.5)
        self.assertEqual(eng.toggle(4.0), ["noff 0"])
        self.assertFalse(eng.recording)
        self.assertEqual(eng.loop.length, 4.0)
        self.assertEqual(eng.loop.anchor, 0.0)
        self.assertEqual(
            [(e.phase, e.cmd) for e in eng.loop.tracks[0].events],
            [(1.0, "n 0 60 100"), (1.5, "x 0 60")],
        )

    def test_phase_during_loop(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.5)
        eng.record("x 0 60", 0, 60, 0.6)
        eng.toggle(4.0)
        self.assertAlmostEqual(eng.phase(5.0), 1.0)
        self.assertAlmostEqual(eng.phase(7.9), 3.9)

    def test_held_note_closed_at_stop(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 1.0)
        eng.record("n 0 64 100", 0, 64, 2.0)
        eng.record("x 0 64", 0, 64, 2.5)
        eng.toggle(4.0)
        events = sorted(eng.loop.tracks[0].events, key=lambda e: e.phase)
        self.assertEqual(
            [e.cmd for e in events],
            ["x 0 60", "n 0 60 100", "n 0 64 100", "x 0 64"],
        )
        self.assertEqual(events[0].phase, 0.0)

    def test_empty_take_starts_no_loop(self):
        eng = Engine()
        eng.toggle(0.0)
        self.assertEqual(eng.toggle(5.0), [])
        self.assertEqual(eng.loop.length, 0.0)
        self.assertEqual(eng.loop.tracks, {})
        self.assertIsNone(eng.loop.anchor)

    def test_empty_take_with_override_starts_no_loop(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        self.assertEqual(eng.toggle(5.0), [])
        self.assertEqual(eng.loop.length, 0.0)
        self.assertEqual(eng.loop.tracks, {})
        self.assertIsNone(eng.loop.anchor)


class TestTakeElapsed(unittest.TestCase):
    def test_none_when_not_recording(self):
        eng = Engine()
        self.assertIsNone(eng.take_elapsed(100.0))

    def test_counts_from_take_start(self):
        eng = Engine()
        eng.toggle(10.0)
        self.assertAlmostEqual(eng.take_elapsed(12.5), 2.5)

    def test_none_after_take_stops(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 1.0)
        eng.toggle(4.0)
        self.assertIsNone(eng.take_elapsed(5.0))


class TestEngineOverdub(unittest.TestCase):
    def _fresh(self, eng):
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.5)
        eng.record("x 0 60", 0, 60, 0.6)
        eng.toggle(4.0)

    def test_overdub_stamps_mod_phase_with_rate(self):
        eng = Engine()
        self._fresh(eng)
        eng.set_rate(2.0)
        eng.override_ch = 1
        self.assertEqual(eng.toggle(10.0), [])
        eng.record("n 1 67 90", 1, 67, 10.75)  # (10.75-0)*2 = 21.5 % 4 = 1.5
        eng.record("x 1 67", 1, 67, 11.25)      # 22.5 % 4 = 2.5
        self.assertEqual(eng.toggle(12.0), ["noff 1"])
        self.assertEqual(eng.loop.length, 4.0)
        self.assertEqual(
            [(e.phase, e.cmd) for e in eng.loop.tracks[1].events],
            [(1.5, "n 1 67 90"), (2.5, "x 1 67")],
        )

    def test_single_channel_take_other_channels_pass(self):
        eng = Engine()
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 1.0)   # locks ch 0
        eng.record("n 3 40 100", 3, 40, 1.5)   # other channel: not recorded
        eng.record("v 3 64", 3, None, 2.0)
        eng.toggle(4.0)
        self.assertEqual(set(eng.loop.tracks), {0})
        self.assertEqual(
            [(e.phase, e.cmd) for e in eng.loop.tracks[0].events],
            [(0.0, "x 0 60"), (1.0, "n 0 60 100")],
        )

    def test_g_and_panic_not_recorded(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("g 0 12", 0, None, 0.5)
        eng.record("panic 0", 0, None, 0.6)
        eng.record("v 0 64", 0, None, 0.7)
        eng.toggle(4.0)
        self.assertEqual([e.cmd for e in eng.loop.tracks[0].events], ["v 0 64"])


class TestEngineReRecord(unittest.TestCase):
    def _loop(self, eng):
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.5)
        eng.record("x 0 60", 0, 60, 0.6)
        eng.toggle(4.0)

    def test_rerecord_mutes_old_track_and_noff(self):
        eng = Engine()
        self._loop(eng)
        eng.override_ch = 0
        self.assertEqual(eng.toggle(10.0), ["noff 0"])
        self.assertTrue(eng.loop.tracks[0].muted)
        eng.record("n 0 65 100", 0, 65, 10.5)
        eng.record("x 0 65", 0, 65, 11.0)
        self.assertEqual(eng.toggle(14.0), ["noff 0"])
        self.assertEqual(eng.loop.length, 4.0)  # lone-track re-record: fresh length
        self.assertEqual(
            [(e.phase, e.cmd) for e in eng.loop.tracks[0].events],
            [(0.5, "n 0 65 100"), (1.0, "x 0 65")],
        )
        self.assertFalse(eng.loop.tracks[0].muted)  # prior mute state inherited

    def test_cancel_restores_prior_mute(self):
        eng = Engine()
        self._loop(eng)
        eng.loop.tracks[0].muted = True  # prior mute state (toggle_mute lands in Task 5)
        eng.override_ch = 0
        self.assertEqual(eng.toggle(10.0), ["noff 0"])
        self.assertTrue(eng.loop.tracks[0].muted)
        eng.record("n 0 65 100", 0, 65, 10.5)
        eng.cancel()
        self.assertFalse(eng.recording)
        self.assertTrue(eng.loop.tracks[0].muted)  # prior mute restored
        self.assertEqual(eng.loop.length, 4.0)
        self.assertEqual(
            [(e.phase, e.cmd) for e in eng.loop.tracks[0].events],
            [(0.5, "n 0 60 100"), (0.6, "x 0 60")],
        )

    def test_cancel_restores_unmuted(self):
        eng = Engine()
        self._loop(eng)
        self.assertFalse(eng.loop.tracks[0].muted)
        eng.override_ch = 0
        eng.toggle(10.0)
        self.assertTrue(eng.loop.tracks[0].muted)  # muted for the take
        eng.record("n 0 65 100", 0, 65, 10.5)
        eng.cancel()
        self.assertFalse(eng.loop.tracks[0].muted)  # prior state restored
        self.assertEqual(eng.loop.length, 4.0)

    def test_rerecord_committed_track_inherits_prior_mute(self):
        eng = Engine()
        self._loop(eng)
        eng.loop.tracks[0].muted = True  # prior mute state
        eng.override_ch = 0
        self.assertEqual(eng.toggle(10.0), ["noff 0"])
        eng.record("n 0 65 100", 0, 65, 10.5)
        eng.record("x 0 65", 0, 65, 11.0)
        self.assertEqual(eng.toggle(14.0), ["noff 0"])
        self.assertTrue(eng.loop.tracks[0].muted)  # prior mute state inherited on commit

    def test_speculative_lone_track_rerecord(self):
        eng = Engine()
        self._loop(eng)
        eng.override_ch = None  # no override: speculative survivor re-record
        self.assertEqual(eng.toggle(10.0), ["noff 0"])
        self.assertTrue(eng.loop.tracks[0].muted)
        eng.record("n 0 65 100", 0, 65, 10.5)
        eng.record("x 0 65", 0, 65, 11.0)
        self.assertEqual(eng.toggle(14.0), ["noff 0"])
        self.assertEqual(eng.loop.length, 4.0)
        self.assertEqual(
            [(e.phase, e.cmd) for e in eng.loop.tracks[0].events],
            [(0.5, "n 0 65 100"), (1.0, "x 0 65")],
        )

    def test_speculative_take_on_other_channel_is_overdub(self):
        eng = Engine()
        self._loop(eng)
        eng.override_ch = None  # no override: lone track muted speculatively
        eng.toggle(10.0)
        eng.record("n 3 40 100", 3, 40, 12.5)  # locks ch 3 (12.5 % 4 = 0.5)
        self.assertFalse(eng.loop.tracks[0].muted)  # speculative mute undone
        eng.record("x 3 40", 3, 40, 13.0)           # 13.0 % 4 = 1.0
        eng.toggle(14.0)
        self.assertEqual(set(eng.loop.tracks), {0, 3})
        self.assertEqual(eng.loop.length, 4.0)  # overdub: existing length kept
        self.assertEqual(
            [(e.phase, e.cmd) for e in eng.loop.tracks[3].events],
            [(0.5, "n 3 40 100"), (1.0, "x 3 40")],
        )
        self.assertFalse(eng.loop.tracks[0].muted)

    def test_seam_wrap_off_before_on(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.5)
        eng.record("x 0 60", 0, 60, 0.6)
        eng.toggle(4.0)
        eng.override_ch = 1
        eng.toggle(6.0)
        eng.record("n 1 72 90", 1, 72, 6.5)
        eng.record("x 1 72", 1, 72, 6.7)
        eng.toggle(8.0)
        eng.override_ch = 0
        self.assertEqual(eng.toggle(10.0), ["noff 0"])  # 2 tracks: overdub
        eng.record("n 0 60 100", 0, 60, 13.8)  # 13.8 % 4 = 1.8
        eng.record("x 0 60", 0, 60, 16.1)       # 16.1 % 4 = 0.1  (off < on: seam)
        eng.toggle(16.5)
        self.assertEqual(
            [(round(e.phase, 6), e.cmd) for e in eng.loop.tracks[0].events],
            [(0.1, "x 0 60"), (1.8, "n 0 60 100")],
        )


class TestEngineEdit(unittest.TestCase):
    def _loop(self, eng):
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.5)
        eng.record("x 0 60", 0, 60, 0.6)
        eng.toggle(4.0)
        eng.override_ch = 1
        eng.toggle(6.0)
        eng.record("n 1 72 90", 1, 72, 6.5)
        eng.record("x 1 72", 1, 72, 6.7)
        eng.toggle(8.0)

    def test_delete_track_returns_noff_and_resets_when_empty(self):
        eng = Engine()
        self._loop(eng)
        self.assertEqual(eng.delete_track(0), ["noff 0"])
        self.assertNotIn(0, eng.loop.tracks)
        self.assertEqual(eng.loop.length, 4.0)  # one track remains: loop survives
        self.assertEqual(eng.delete_track(1), ["noff 1"])
        self.assertEqual(eng.loop.tracks, {})
        self.assertEqual(eng.loop.length, 0.0)  # reset
        self.assertIsNone(eng.loop.anchor)

    def test_delete_missing_channel_noop(self):
        eng = Engine()
        self.assertEqual(eng.delete_track(3), [])

    def test_toggle_mute_returns_noff_and_flips(self):
        eng = Engine()
        self._loop(eng)
        self.assertEqual(eng.toggle_mute(0), ["noff 0"])
        self.assertTrue(eng.loop.tracks[0].muted)
        self.assertEqual(eng.toggle_mute(0), ["noff 0"])
        self.assertFalse(eng.loop.tracks[0].muted)
        self.assertEqual(eng.toggle_mute(9), [])


class TestEngineRateHalt(unittest.TestCase):
    def _loop(self, eng):
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 1.0)
        eng.record("x 0 60", 0, 60, 2.0)
        eng.record("n 0 60 100", 0, 60, 3.0)
        eng.record("x 0 60", 0, 60, 3.5)
        eng.toggle(4.0)

    def test_set_rate_clamps(self):
        eng = Engine()
        eng.set_rate(10.0)
        self.assertEqual(eng.rate, 4.0)
        eng.set_rate(0.1)
        self.assertEqual(eng.rate, 0.25)
        eng.set_rate(2.0)
        self.assertEqual(eng.rate, 2.0)

    def test_halt_freezes_phase_and_resume_continues(self):
        eng = Engine()
        self._loop(eng)
        eng.phase(1.5)
        self.assertEqual(eng.halt(), ["panic"])
        self.assertAlmostEqual(eng.phase(100.0), 1.5)
        self.assertEqual(eng.toggle(100.0), [])
        eng.resume(100.0)
        self.assertAlmostEqual(eng.phase(100.0), 1.5)
        self.assertAlmostEqual(eng.phase(101.0), 2.5)

    def test_halt_during_take_only_panics(self):
        eng = Engine()
        self._loop(eng)
        eng.override_ch = 0
        eng.toggle(10.0)
        self.assertEqual(eng.halt(), ["panic"])
        self.assertAlmostEqual(eng.phase(11.0), 3.0)
        eng.record("n 0 65 100", 0, 65, 10.5)
        self.assertEqual(eng.toggle(14.0), ["noff 0"])
        self.assertAlmostEqual(eng.phase(14.1), 0.1)

    def test_halt_without_loop_just_panics(self):
        eng = Engine()
        self.assertEqual(eng.halt(), ["panic"])
        self.assertIsNone(eng.phase(1.0))

    def test_resume_when_not_halted_is_noop(self):
        eng = Engine()
        eng.resume(1.0)

    def test_halted_property(self):
        eng = Engine()
        self.assertFalse(eng.halted)
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.5)
        eng.record("x 0 60", 0, 60, 0.6)
        eng.toggle(4.0)
        eng.phase(1.0)
        eng.halt()
        self.assertTrue(eng.halted)
        eng.resume(5.0)
        self.assertFalse(eng.halted)


class TestEngineOverRecord(unittest.TestCase):
    def _two_track_loop(self, eng):
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.5)
        eng.record("x 0 60", 0, 60, 0.6)
        eng.toggle(4.0)
        eng.override_ch = 1
        eng.toggle(6.0)
        eng.record("n 1 72 90", 1, 72, 6.5)
        eng.record("x 1 72", 1, 72, 6.7)
        eng.toggle(8.0)

    def test_final_pass_wins(self):
        eng = Engine()
        self._two_track_loop(eng)
        self.assertEqual(eng.loop.length, 4.0)
        eng.override_ch = 0
        self.assertEqual(eng.toggle(10.0), ["noff 0"])  # overdub: 2 tracks remain
        eng.record("n 0 60 100", 0, 60, 10.2)   # t 10.2, phase 0.2 - dropped
        eng.record("x 0 60", 0, 60, 10.3)        # t 10.3, phase 0.3 - dropped
        eng.record("n 0 65 100", 0, 65, 11.0)   # t 11.0, phase 3.0 - kept
        eng.record("x 0 65", 0, 65, 11.1)        # t 11.1, phase 3.1 - kept
        eng.record("n 0 60 100", 0, 60, 14.2)   # t 14.2, phase 2.2 - kept
        eng.record("x 0 60", 0, 60, 14.3)        # t 14.3, phase 2.3 - kept
        eng.toggle(14.5)                         # final_start = 14.5 - 4 = 10.5
        self.assertEqual(
            [(round(e.phase, 6), e.cmd)
             for e in sorted(eng.loop.tracks[0].events, key=lambda e: e.phase)],
            [
                (2.2, "n 0 60 100"),
                (2.3, "x 0 60"),
                (3.0, "n 0 65 100"),
                (3.1, "x 0 65"),
            ],
        )

    def test_seam_note_held_across_wrap_kept(self):
        eng = Engine()
        self._two_track_loop(eng)
        eng.override_ch = 0
        eng.toggle(10.0)
        eng.record("n 0 60 100", 0, 60, 10.05)  # t 10.05 < final_start 10.2: dropped
        eng.toggle(14.2)                        # still held: closing x at stop phase 2.2
        self.assertEqual(
            [(round(e.phase, 6), e.cmd)
             for e in sorted(eng.loop.tracks[0].events, key=lambda e: e.phase)],
            [(2.05, "n 0 60 100"), (2.2, "x 0 60")],  # seam-close keeps the on
        )


class TestEngineDue(unittest.TestCase):
    def _loop(self, eng):
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.0)
        eng.record("x 0 60", 0, 60, 0.5)
        eng.record("n 0 64 100", 0, 64, 1.0)
        eng.record("x 0 64", 0, 64, 1.5)
        eng.toggle(4.0)

    def _two_track(self, eng):
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.5)
        eng.record("x 0 60", 0, 60, 0.6)
        eng.toggle(4.0)
        eng.override_ch = 1
        eng.toggle(6.0)
        eng.record("n 1 72 90", 1, 72, 6.5)
        eng.record("x 1 72", 1, 72, 6.7)
        eng.toggle(8.0)

    def test_due_empty_loop(self):
        eng = Engine()
        self.assertEqual(eng.due(0.0), [])

    def test_due_emits_in_phase_seq_order(self):
        eng = Engine()
        self._loop(eng)
        self.assertEqual([e.cmd for e in eng.due(0.0)], ["n 0 60 100"])
        self.assertEqual([e.cmd for e in eng.due(0.6)], ["x 0 60"])
        self.assertEqual([e.cmd for e in eng.due(1.2)], ["n 0 64 100"])
        self.assertEqual([e.cmd for e in eng.due(1.7)], ["x 0 64"])
        self.assertEqual(eng.due(2.0), [])
        self.assertEqual([e.cmd for e in eng.due(4.1)], ["n 0 60 100"])  # wrap: phase 0
        self.assertEqual([e.cmd for e in eng.due(4.6)], ["x 0 60"])

    def test_same_phase_burst_ordered_by_seq(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        # Distinct notes at the same phase, so the off==on seam clamp does not
        # defer any of these offs; notes 60/61 are released at phase 2.0 so the
        # stop does not synthesize same-channel closing offs at phase 0.
        eng.record("n 0 60 100", 0, 60, 1.0)
        eng.record("n 0 61 100", 0, 61, 1.0)
        eng.record("x 0 62", 0, 62, 1.0)
        eng.record("x 0 63", 0, 63, 1.0)
        eng.record("x 0 60", 0, 60, 2.0)
        eng.record("x 0 61", 0, 61, 2.0)
        eng.toggle(4.0)
        self.assertEqual(
            [e.cmd for e in eng.due(1.2)],
            ["n 0 60 100", "n 0 61 100", "x 0 62", "x 0 63"],
        )

    def test_seam_clamp_full_length_note(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.5)
        eng.record("x 0 60", 0, 60, 0.5)  # off == on: ambiguous -> full-length note
        eng.toggle(4.0)
        self.assertEqual([e.cmd for e in eng.due(0.5)], ["n 0 60 100"])  # off deferred
        self.assertEqual(eng.due(1.0), [])
        self.assertEqual(eng.due(2.0), [])
        self.assertEqual(eng.due(4.1), [])
        self.assertEqual([e.cmd for e in eng.due(4.6)],
                         ["n 0 60 100", "x 0 60"])  # off fires one cycle later

    def test_muted_track_skipped_in_due(self):
        eng = Engine()
        self._two_track(eng)
        eng.toggle_mute(1)
        self.assertEqual([e.cmd for e in eng.due(7.0)],
                         ["n 0 60 100", "x 0 60"])

    def test_resume_continues_due_emission(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 1.0)
        eng.record("x 0 60", 0, 60, 2.0)
        eng.record("n 0 60 100", 0, 60, 3.0)
        eng.record("x 0 60", 0, 60, 3.5)
        eng.toggle(4.0)
        self.assertEqual([e.cmd for e in eng.due(0.5)], [])
        self.assertEqual([e.cmd for e in eng.due(1.5)], ["n 0 60 100"])
        self.assertEqual([e.cmd for e in eng.due(2.5)], ["x 0 60"])
        self.assertEqual(eng.halt(), ["panic"])
        eng.resume(100.0)
        self.assertEqual([e.cmd for e in eng.due(100.5)], ["n 0 60 100"])  # phase 3.0
        self.assertEqual([e.cmd for e in eng.due(101.0)], ["x 0 60"])      # phase 3.5


class TestEngineRoundTrip(unittest.TestCase):
    def test_recorded_events_play_back(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.0)
        eng.record("x 0 60", 0, 60, 0.5)
        eng.record("n 0 64 100", 0, 64, 1.0)
        eng.record("x 0 64", 0, 64, 1.5)
        eng.toggle(4.0)
        played = []
        for t in (0.0, 0.6, 1.2, 1.7, 2.5, 4.1, 4.6, 5.2, 5.7):
            played += [e.cmd for e in eng.due(t)]
        self.assertEqual(
            played,
            [
                "n 0 60 100", "x 0 60", "n 0 64 100", "x 0 64",
                "n 0 60 100", "x 0 60", "n 0 64 100", "x 0 64",
            ],
        )

    def test_engine_builds_loop_that_round_trips(self):
        eng = Engine()
        eng.override_ch = 0
        eng.toggle(0.0)
        eng.record("n 0 60 100", 0, 60, 0.0)
        eng.record("x 0 60", 0, 60, 0.5)
        eng.record("n 0 64 100", 0, 64, 1.0)
        eng.record("x 0 64", 0, 64, 1.5)
        eng.toggle(4.0)
        eng.override_ch = 1
        eng.toggle(6.0)
        eng.record("n 1 72 90", 1, 72, 6.5)  # 6.5 % 4 = 2.5
        eng.record("x 1 72", 1, 72, 6.7)       # 6.7 % 4 = 2.7
        eng.toggle(8.0)
        eng.toggle_mute(0)
        restored = loop_from_text(loop_to_text(eng.loop))
        self.assertEqual(restored.length, 4.0)
        self.assertIsNone(restored.anchor)
        self.assertTrue(restored.tracks[0].muted)
        self.assertEqual(
            [(e.phase, e.cmd) for e in restored.tracks[0].events],
            [(0.0, "n 0 60 100"), (0.5, "x 0 60"), (1.0, "n 0 64 100"), (1.5, "x 0 64")],
        )
        self.assertEqual(
            [(e.phase, e.cmd) for e in restored.tracks[1].events],
            [(2.5, "n 1 72 90"), (2.7, "x 1 72")],
        )

    def test_engine_continues_seq_from_loaded_loop(self):
        text = "reduzent-loop v1\nlength 4.000000\n0.500000 n 0 60 100\n0.600000 x 0 60\n"
        eng = Engine(loop_from_text(text))
        eng.loop.anchor = 6.0  # the runtime sets the anchor to the load moment
        eng.override_ch = 1
        eng.toggle(6.0)
        eng.record("n 1 72 90", 1, 72, 6.5)
        eng.record("x 1 72", 1, 72, 6.7)
        eng.toggle(8.0)
        self.assertEqual(eng.loop.length, 4.0)
        self.assertEqual([e.seq for e in eng.loop.tracks[1].events], [2, 3])


class TestRuntimeHelpers(unittest.TestCase):
    def test_sanitize_name(self):
        self.assertEqual(sanitize_name("My Jam!"), "my-jam")
        self.assertEqual(sanitize_name("  spaces  here "), "spaces-here")
        self.assertEqual(sanitize_name("a_b-c2"), "a_b-c2")
        self.assertEqual(sanitize_name("!!!###"), "")

    def test_loop_path(self):
        self.assertEqual(loop_path("/base", "jam"), "/base/jam/loop.loop")

    def test_named_save_load_and_list(self):
        loop = Loop(length=4.0)
        loop.tracks[0] = Track(events=[Event(phase=0.5, seq=0, cmd="n 0 60 100")])
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(list_loop_names(d), [])
            save_loop_named(d, "jam1", loop)
            save_loop_named(d, "jam2", loop)
            os.makedirs(os.path.join(d, "notaloop"))  # no loop.loop: not listed
            self.assertEqual(list_loop_names(d), ["jam1", "jam2"])
            self.assertEqual(load_loop_named(d, "jam1"), loop)

    def test_named_load_missing_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                load_loop_named(d, "missing")


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class TestStatusLines(unittest.TestCase):
    @staticmethod
    def _plain(text):
        return _ANSI_RE.sub("", text)

    def test_no_loop_defaults(self):
        line1, line2 = status_lines("/dev/ttyUSB0", 115200, None, Loop(), 1.0,
                                    None, None, None, None)
        line1, line2 = self._plain(line1), self._plain(line2)
        self.assertIn("/dev/ttyUSB0", line1)
        self.assertIn("loop: no loop", line1)
        self.assertIn("trk: 0", line1)
        self.assertIn("rate: x1.00", line1)
        self.assertIn("ch: --", line2)

    def test_loop_overrides_and_rate(self):
        loop = Loop(length=4.0)
        loop.tracks[0] = Track()
        loop.tracks[3] = Track()
        line1, line2 = status_lines("p", 9600, "jam1", loop, 2.0,
                                    2, None, 0, selected=5)
        line1, line2 = self._plain(line1), self._plain(line2)
        self.assertIn("jam1", line1)
        self.assertIn("4.00s", line1)
        self.assertIn("trk: 2", line1)
        self.assertIn("rate: x2.00", line1)
        self.assertIn("sel: 5", line2)  # selection is the active channel
        self.assertIn("inst: 1-bit", line2)

    def test_override_inst_and_midi_channel(self):
        loop = Loop()
        line1, line2 = status_lines("p", 9600, None, loop, 1.0,
                                    3, 7, None)
        line1, line2 = self._plain(line1), self._plain(line2)
        self.assertIn("ch: 3", line2)
        self.assertIn("(MIDI)", line2)
        self.assertIn("inst: 7", line2)

    def test_recording_shows_indicator_and_clock(self):
        line1, _ = status_lines("p", 9600, None, Loop(), 1.0,
                                None, None, None,
                                recording=True, rec_elapsed=65.0)
        plain = self._plain(line1)
        self.assertIn("\u25cf REC", plain)
        self.assertIn("1:05", plain)

    def test_not_recording_has_no_indicator(self):
        line1, _ = status_lines("p", 9600, None, Loop(), 1.0,
                                None, None, None, None)
        self.assertNotIn("REC", self._plain(line1))

    def test_rec_blink_visible_phase(self):
        line1, _ = status_lines("p", 9600, None, Loop(), 1.0,
                                None, None, None,
                                recording=True, rec_elapsed=0.2)
        plain = self._plain(line1)
        self.assertIn("\u25cf REC", plain)
        self.assertIn("0:00", plain)  # clock stays up while the label blinks

    def test_rec_blink_hidden_phase(self):
        line1, _ = status_lines("p", 9600, None, Loop(), 1.0,
                                None, None, None,
                                recording=True, rec_elapsed=0.7)
        plain = self._plain(line1)
        self.assertNotIn("\u25cf REC", plain)
        self.assertIn("0:00", plain)

    def test_rec_blink_keeps_line_width(self):
        on, _ = status_lines("p", 9600, None, Loop(), 1.0,
                             None, None, None,
                             recording=True, rec_elapsed=0.2)
        off, _ = status_lines("p", 9600, None, Loop(), 1.0,
                              None, None, None,
                              recording=True, rec_elapsed=0.7)
        # Hidden phase reserves the label's columns so the line never jumps.
        self.assertEqual(len(self._plain(on)), len(self._plain(off)))

    def test_rec_clock_truncates_subsecond(self):
        line1, _ = status_lines("p", 9600, None, Loop(), 1.0,
                                None, None, None,
                                recording=True, rec_elapsed=5.9)
        self.assertIn("0:05", self._plain(line1))


class TestTruncateVisible(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(_truncate_visible("hello", 10), "hello")
        self.assertEqual(_visible_len("hello"), 5)

    def test_plain_truncation(self):
        self.assertEqual(_truncate_visible("hello", 3), "hel")

    def test_wide_unicode_counts_one_column(self):
        self.assertEqual(_visible_len("→"), 1)
        self.assertEqual(_truncate_visible("a→b", 2), "a→")

    def test_ansi_sequences_zero_width_and_preserved(self):
        text = "\033[1;31mREC\033[0m"
        self.assertEqual(_visible_len(text), 3)
        self.assertEqual(_truncate_visible(text, 2), "\033[1;31mRE\033[0m")

    def test_width_zero_and_negative(self):
        self.assertEqual(_truncate_visible("abc", 0), "")
        self.assertEqual(_truncate_visible("abc", -1), "")

    def test_cut_inside_escape_keeps_sequence_intact(self):
        text = "\033[1;33msel\033[0m rest"
        # The final reset is added back when the cut happens inside attributes.
        self.assertEqual(_truncate_visible(text, 4), "\033[1;33msel\033[0m \033[0m")
        self.assertEqual(_truncate_visible(text, 5), "\033[1;33msel\033[0m r\033[0m")


class TestStatusLineWidth(unittest.TestCase):
    @staticmethod
    def _plain(text):
        return _ANSI_RE.sub("", text)

    def test_width_truncates_both_lines(self):
        loop = Loop(length=1.0)
        line1, line2 = status_lines("/dev/ttyS0", 115200, None, loop, 1.0,
                                    None, None, None,
                                    selected=0, sel_name="Drums", width=40)
        for line in (line1, line2):
            self.assertLessEqual(len(self._plain(line)), 40)

    def test_no_width_leaves_full_help(self):
        line1, line2 = status_lines("/dev/ttyS0", 115200, None, Loop(), 1.0,
                                    None, None, None, None, selected=0,
                                    sel_name="Drums")
        self.assertIn("q quit", self._plain(line2))  # tail of help survives

    def test_selection_prefix_survives_truncation(self):
        line1, line2 = status_lines("/dev/ttyS0", 115200, None, Loop(), 1.0,
                                    None, None, None, None, selected=3,
                                    sel_name="Piezo L", width=30)
        plain = self._plain(line2)
        self.assertIn("sel: Piezo L", plain)


class TestParseChannels(unittest.TestCase):
    def test_absent_key_returns_none(self):
        chans, warns = parse_channels({})
        self.assertIsNone(chans)
        self.assertEqual(warns, [])

    def test_valid_map(self):
        chans, warns = parse_channels({"channels": {"0": "kick", "5": "bass"}})
        self.assertEqual(chans, {0: "kick", 5: "bass"})
        self.assertEqual(warns, [])

    def test_invalid_entries_dropped_with_warning(self):
        chans, warns = parse_channels(
            {"channels": {"0": "kick", "99": "bad", "x": "bad", "2": ""}}
        )
        self.assertEqual(chans, {0: "kick"})
        self.assertEqual(len(warns), 3)

    def test_all_invalid_returns_none(self):
        chans, warns = parse_channels({"channels": {"99": "bad"}})
        self.assertIsNone(chans)
        self.assertEqual(len(warns), 1)

    def test_name_sanitized_single_line_truncated(self):
        chans, _ = parse_channels({"channels": {"1": "a\nb\r  cdefghij"}})
        self.assertEqual(chans, {1: "a b cdef"})


class TestParseHotkeys(unittest.TestCase):
    def test_absent_key_returns_empty(self):
        hk, warns = parse_hotkeys({})
        self.assertEqual(hk, {})
        self.assertEqual(warns, [])

    def test_valid_hotkeys(self):
        hk, warns = parse_hotkeys(
            {"midi_hotkeys": {
                "record": {"channel": 15, "note": 60},
                "cycle": {"channel": 15, "note": 62},
            }}
        )
        self.assertEqual(hk, {"record": (15, 60), "cycle": (15, 62)})
        self.assertEqual(warns, [])

    def test_bad_entries_dropped_with_warning(self):
        hk, warns = parse_hotkeys(
            {"midi_hotkeys": {
                "record": {"channel": 15, "note": 60},
                "explode": {"channel": 0, "note": 1},   # unknown action
                "cycle": {"channel": 16, "note": 62},   # channel out of range
                "record2": None,
            }}
        )
        self.assertEqual(hk, {"record": (15, 60)})
        self.assertEqual(len(warns), 3)


class TestPresentChannels(unittest.TestCase):
    def test_config_wins_sorted(self):
        loop = Loop(tracks={3: Track(), 1: Track()})
        self.assertEqual(present_channels({5: "a", 2: "b"}, loop), [2, 5])

    def test_fallback_to_tracks(self):
        loop = Loop(tracks={3: Track(), 1: Track()})
        self.assertEqual(present_channels(None, loop), [1, 3])

    def test_both_empty(self):
        self.assertEqual(present_channels(None, Loop()), [])


class TestStepChannel(unittest.TestCase):
    def test_wrap_forward_and_back(self):
        self.assertEqual(step_channel(5, [1, 3, 5], 1), 1)
        self.assertEqual(step_channel(1, [1, 3, 5], -1), 5)

    def test_neighbor(self):
        self.assertEqual(step_channel(3, [1, 3, 5], 1), 5)
        self.assertEqual(step_channel(3, [1, 3, 5], -1), 1)

    def test_none_or_foreign_cur_starts_at_first(self):
        self.assertEqual(step_channel(None, [1, 3], 1), 1)
        self.assertEqual(step_channel(9, [1, 3], -1), 1)

    def test_empty_present_returns_none(self):
        self.assertIsNone(step_channel(1, [], 1))

    def test_single_element_stays(self):
        self.assertEqual(step_channel(1, [1], 1), 1)


class TestEditTarget(unittest.TestCase):
    def test_precedence(self):
        """Selection (the active channel) wins, else the last MIDI channel."""
        self.assertEqual(edit_target(2, 9), 2)
        self.assertEqual(edit_target(None, 9), 9)
        self.assertIsNone(edit_target(None, None))


class TestHotkeyAction(unittest.TestCase):
    HK = {"record": (15, 60), "cycle": (15, 62)}

    def test_note_on_matches(self):
        self.assertEqual(hotkey_action(self.HK, "note_on", 15, 60, 100), "record")
        self.assertEqual(hotkey_action(self.HK, "note_on", 15, 62, 1), "cycle")

    def test_wrong_channel_or_note_passes_through(self):
        self.assertIsNone(hotkey_action(self.HK, "note_on", 0, 60, 100))
        self.assertIsNone(hotkey_action(self.HK, "note_on", 15, 61, 100))

    def test_note_off_is_swallowed(self):
        self.assertEqual(hotkey_action(self.HK, "note_off", 15, 60, 0), "swallow")

    def test_velocity_zero_note_on_is_swallowed(self):
        self.assertEqual(hotkey_action(self.HK, "note_on", 15, 60, 0), "swallow")

    def test_empty_hotkeys_never_match(self):
        self.assertIsNone(hotkey_action({}, "note_on", 15, 60, 100))


class TestColumnLines(unittest.TestCase):
    def build(self, tracks, selected=None, names=None, blink=True, max_rows=20):
        return column_lines(sorted(tracks), Loop(tracks=tracks), selected,
                            names, max_rows, blink)

    def test_untracked_dim_tracked_plain(self):
        loop = Loop(tracks={1: Track()})
        lines = column_lines([0, 1], loop, None, None, 20, True)
        self.assertTrue(lines[0].startswith("\033[2m"))       # ch 0 untracked dim
        self.assertIn("0", lines[0])
        self.assertEqual(lines[1].strip(), "1")               # ch 1 plain

    def test_muted_marker(self):
        t = Track(); t.muted = True
        self.assertIn("*", self.build({0: t})[0])

    def test_selected_blink_highlight(self):
        line = self.build({0: Track()}, selected=0)[0]
        self.assertTrue(line.startswith("\033[1;31;7m"))
        self.assertTrue(line.endswith("\033[0m"))

    def test_selected_not_blinking_is_plain_bright(self):
        line = self.build({0: Track()}, selected=0, blink=False)[0]
        self.assertNotIn("7m", line)

    def test_names_used_numbers_fallback(self):
        lines = self.build({0: Track()}, names={0: "kick"})
        self.assertIn("kick", lines[0])
        self.assertIn("0:", lines[0])        # channel number always shown
        self.assertIn("0", self.build({0: Track()})[0])

    def test_all_cells_same_width(self):
        """Short vs long names must not shift the column (no jumping)."""
        names = {0: "A", 1: "Piezo S", 2: "Piezo M", 3: "Piezo L"}
        loop = Loop(tracks={})
        lines = column_lines([0, 1, 2, 3], loop, 0, names, 20, True)
        widths = {_visible_len(l) for l in lines}
        self.assertEqual(len(widths), 1)     # every line identical width

    def test_overflow_marker(self):
        tracks = {ch: Track() for ch in range(6)}
        lines = self.build(tracks, max_rows=3)
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[-1].strip(), "+4 more")


class TestStatusLineSelection(unittest.TestCase):
    def base(self, **kw):
        # Defaults go in as keywords so callers may override any of them
        # (duplicate positional binding would raise TypeError); lines come
        # back ANSI-stripped like TestStatusLines._plain.
        kw.setdefault("last_channel", None)
        kw.setdefault("override_inst", None)
        kw.setdefault("last_program", None)
        line1, line2 = status_lines("/dev/ttyUSB0", 115200, None, Loop(),
                                    1.0, **kw)
        return _ANSI_RE.sub("", line1), _ANSI_RE.sub("", line2)

    def test_no_selection_keeps_old_rendering(self):
        _, line2 = self.base(last_channel=3)
        self.assertIn("ch: 3 (MIDI)", line2)

    def test_selection_shows_name(self):
        # The selection is the active channel; no separate override tag.
        _, line2 = self.base(selected=1, sel_name="snare")
        self.assertIn("sel: snare", line2)
        self.assertNotIn("ovr", line2)
        self.assertNotIn("override", line2)

    def test_selection_without_name_shows_number(self):
        _, line2 = self.base(selected=7)
        self.assertIn("sel: 7 ", line2)

    def test_help_mentions_new_keys_not_zero_reset(self):
        _, line2 = self.base()
        self.assertIn("0-9", line2)
        self.assertIn("nav", line2)
        self.assertNotIn("0 reset", line2)


if __name__ == "__main__":
    unittest.main()
