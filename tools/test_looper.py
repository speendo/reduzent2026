#!/usr/bin/env python3
"""Unit tests for tools/looper.py — model + save format (slice 2).

Covers the Loop/Track/Event model, the reduzent-loop v1 text serializer
(loop_to_text / loop_from_text), and the save_loop / load_loop file wrappers.
Run:

    python3 tools/test_looper.py
"""

import unittest

from looper import Event, Track, Loop, loop_to_text, loop_from_text


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


if __name__ == "__main__":
    unittest.main()
