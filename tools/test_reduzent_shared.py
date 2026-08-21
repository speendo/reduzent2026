#!/usr/bin/env python3
"""Unit tests for tools/reduzent_shared.py.

Covers `raw_terminal` directly on a pty (a real tty, no display or session
needed). The moved pure functions (midi_to_command, settings) are covered
transitively by tools/test_midi_bridge.py, which imports them from
midi_bridge.py (which re-exports them from reduzent_shared). Run:

    python3 tools/test_reduzent_shared.py
"""

import json
import os
import pty
import tempfile
import termios
import tty
import unittest
import unittest.mock

import reduzent_shared as rs
from reduzent_shared import find_config, raw_terminal


def _close_pair(master, slave):
    os.close(master)
    os.close(slave)


class TestRawTerminal(unittest.TestCase):
    def test_enters_raw_mode_and_restores_on_exit(self):
        master, slave = pty.openpty()
        try:
            before = termios.tcgetattr(slave)
            with raw_terminal(slave) as old:
                self.assertEqual(old, before)
                raw = termios.tcgetattr(slave)
                self.assertNotEqual(raw, before)
                # Raw mode: echo and canonical processing are off. (Python 3.12
                # leaves ECHOCTL|ECHOKE set via cfmakeraw, so lflag != 0.)
                self.assertEqual(raw[3] & (termios.ECHO | termios.ICANON), 0)
            after = termios.tcgetattr(slave)
            self.assertEqual(after, before)
        finally:
            _close_pair(master, slave)

    def test_restores_on_exception(self):
        master, slave = pty.openpty()
        try:
            before = termios.tcgetattr(slave)
            with self.assertRaises(RuntimeError):
                with raw_terminal(slave):
                    raise RuntimeError("boom")
            self.assertEqual(termios.tcgetattr(slave), before)
        finally:
            _close_pair(master, slave)

    def test_yielded_old_enables_prompt_pattern(self):
        # midi_bridge's prompt pattern: restore `old`, run the prompt, re-enter raw.
        master, slave = pty.openpty()
        try:
            before = termios.tcgetattr(slave)
            with raw_terminal(slave) as old:
                termios.tcsetattr(slave, termios.TCSADRAIN, old)
                self.assertEqual(termios.tcgetattr(slave), before)
                tty.setraw(slave)
                self.assertEqual(
                    termios.tcgetattr(slave)[3] & (termios.ECHO | termios.ICANON), 0
                )
        finally:
            _close_pair(master, slave)


class TestFindConfig(unittest.TestCase):
    """Priority: --config flag > tools/config/ > user config dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = os.path.join(self.tmp.name, "project")
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(os.path.join(self.project, "config"))
        self.proj_cfg = os.path.join(self.project, "config", rs.CONFIG_NAME)
        self.user_cfg = os.path.join(self.home, rs.CONFIG_NAME)

        def fake_candidates():
            return [self.proj_cfg]

        # Point the module at the fake layout for the duration of each test.
        p1 = unittest.mock.patch.object(rs, "_config_candidates", fake_candidates)
        p1.start()
        self.addCleanup(p1.stop)
        p2 = unittest.mock.patch.object(rs, "DEFAULT_CONFIG", self.user_cfg)
        p2.start()
        self.addCleanup(p2.stop)

    def _write(self, path, marker):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"who": marker}, f)

    def test_explicit_flag_wins_even_if_missing(self):
        explicit = os.path.join(self.tmp.name, "explicit.json")
        self._write(self.proj_cfg, "proj")
        got = find_config(explicit)
        self.assertEqual(got, explicit)  # creation target, even before it exists

    def test_project_config_beats_user(self):
        self._write(self.proj_cfg, "proj")
        self._write(self.user_cfg, "user")
        self.assertEqual(find_config(), self.proj_cfg)

    def test_user_config_when_no_project_file(self):
        self._write(self.user_cfg, "user")
        self.assertEqual(find_config(), self.user_cfg)

    def test_new_file_created_in_user_dir(self):
        self.assertEqual(find_config(), self.user_cfg)


if __name__ == "__main__":
    unittest.main()
