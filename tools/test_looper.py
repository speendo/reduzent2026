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
                                    5, 2, None, 0)
        line1, line2 = self._plain(line1), self._plain(line2)
        self.assertIn("jam1", line1)
        self.assertIn("4.00s", line1)
        self.assertIn("trk: 2", line1)
        self.assertIn("rate: x2.00", line1)
        self.assertIn("ch: 5", line2)
        self.assertIn("(override)", line2)
        self.assertIn("inst: 1-bit", line2)

    def test_override_inst_and_midi_channel(self):
        loop = Loop()
        line1, line2 = status_lines("p", 9600, None, loop, 1.0,
                                    None, 3, 7, None)
        line1, line2 = self._plain(line1), self._plain(line2)
        self.assertIn("ch: 3", line2)
        self.assertIn("(MIDI)", line2)
        self.assertIn("inst: 7", line2)


if __name__ == "__main__":
    unittest.main()
