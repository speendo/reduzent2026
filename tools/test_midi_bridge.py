#!/usr/bin/env python3
"""Unit tests for tools/midi_bridge.py.

Covers the pure mapping and settings-file logic only (the interactive menu and
serial/MIDI I/O are exercised manually). Run:

    python3 tools/test_midi_bridge.py
"""

import os
import tempfile
import unittest

import mido

from midi_bridge import (
    load_settings,
    midi_to_command,
    resolve_settings,
    save_settings,
)


class TestMidiToCommand(unittest.TestCase):
    def test_note_on(self):
        m = mido.Message("note_on", channel=0, note=60, velocity=100)
        self.assertEqual(midi_to_command(m), "n 0 60 100")

    def test_note_on_zero_velocity_is_off(self):
        m = mido.Message("note_on", channel=2, note=61, velocity=0)
        self.assertEqual(midi_to_command(m), "x 2 61")

    def test_note_off(self):
        m = mido.Message("note_off", channel=3, note=62, velocity=0)
        self.assertEqual(midi_to_command(m), "x 3 62")

    def test_pitchwheel_center(self):
        m = mido.Message("pitchwheel", channel=1, pitch=0)
        self.assertEqual(midi_to_command(m), "p 1 8192")

    def test_pitchwheel_min(self):
        m = mido.Message("pitchwheel", channel=1, pitch=-8192)
        self.assertEqual(midi_to_command(m), "p 1 0")

    def test_pitchwheel_max(self):
        m = mido.Message("pitchwheel", channel=1, pitch=8191)
        self.assertEqual(midi_to_command(m), "p 1 16383")

    def test_aftertouch(self):
        m = mido.Message("aftertouch", channel=4, value=77)
        self.assertEqual(midi_to_command(m), "a 4 77")

    def test_polytouch(self):
        m = mido.Message("polytouch", channel=5, note=64, value=88)
        self.assertEqual(midi_to_command(m), "pa 5 64 88")

    def test_program_change(self):
        m = mido.Message("program_change", channel=6, program=9)
        self.assertEqual(midi_to_command(m), "g 6 9")

    def test_cc1_vibrato(self):
        m = mido.Message("control_change", channel=7, control=1, value=50)
        self.assertEqual(midi_to_command(m), "v 7 50")

    def test_cc_panic(self):
        for cc in (120, 121, 123):
            m = mido.Message("control_change", channel=0, control=cc, value=0)
            self.assertEqual(midi_to_command(m), "panic", f"cc{cc}")

    def test_other_cc_ignored(self):
        m = mido.Message("control_change", channel=0, control=7, value=64)
        self.assertIsNone(midi_to_command(m))

    def test_system_ignored(self):
        m = mido.Message("clock")
        self.assertIsNone(midi_to_command(m))


class TestSettings(unittest.TestCase):
    def test_load_missing_returns_empty(self):
        self.assertEqual(load_settings("/nonexistent/path/x.json"), {})

    def test_save_load_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "cfg.json")
            save_settings(p, {"midi_input": "A", "serial_port": "B", "baud": 9600})
            self.assertEqual(
                load_settings(p),
                {"midi_input": "A", "serial_port": "B", "baud": 9600},
            )

    def test_resolve_uses_saved(self):
        s = resolve_settings(
            {"midi_input": "KBD", "serial_port": "/dev/ttyUSB0", "baud": 9600},
            ["KBD", "Other"],
            ["/dev/ttyUSB0"],
        )
        self.assertEqual(s, ("KBD", "/dev/ttyUSB0", 9600))

    def test_resolve_drops_stale(self):
        s = resolve_settings(
            {"midi_input": "Gone", "serial_port": "/dev/ttyUSB9"},
            ["KBD"],
            ["/dev/ttyUSB0"],
        )
        self.assertEqual(s, ("KBD", "/dev/ttyUSB0", 115200))


if __name__ == "__main__":
    unittest.main()
