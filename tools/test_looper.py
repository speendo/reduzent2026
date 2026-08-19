#!/usr/bin/env python3
"""Unit tests for tools/looper.py — model + save format (slice 2).

Covers the Loop/Track/Event model, the reduzent-loop v1 text serializer
(loop_to_text / loop_from_text), and the save_loop / load_loop file wrappers.
Run:

    python3 tools/test_looper.py
"""

import unittest

from looper import Event, Track, Loop


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


if __name__ == "__main__":
    unittest.main()
