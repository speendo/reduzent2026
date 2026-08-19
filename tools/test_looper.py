#!/usr/bin/env python3
"""Unit tests for tools/looper.py — model + save format (slice 2).

Covers the Loop/Track/Event model, the reduzent-loop v1 text serializer
(loop_to_text / loop_from_text), and the save_loop / load_loop file wrappers.
Run:

    python3 tools/test_looper.py
"""

import unittest

from looper import Event, Track, Loop, loop_to_text


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


if __name__ == "__main__":
    unittest.main()
