#!/usr/bin/env python3
"""Unit tests for tools/reduzent_shared.py.

Covers `raw_terminal` directly on a pty (a real tty, no display or session
needed). The moved pure functions (midi_to_command, settings) are covered
transitively by tools/test_midi_bridge.py, which imports them from
midi_bridge.py (which re-exports them from reduzent_shared). Run:

    python3 tools/test_reduzent_shared.py
"""

import os
import pty
import termios
import tty
import unittest

from reduzent_shared import raw_terminal


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


if __name__ == "__main__":
    unittest.main()
