#!/usr/bin/env python3
"""Shared helpers for the reduzent2026 tool scripts.

Holds the pure mapping and settings-file logic plus the terminal helpers that
`midi_bridge.py` and `looper.py` share. `midi_bridge.py` re-imports these names
from here; `looper.py` imports from here only (never from `midi_bridge`), so
later changes to `midi_bridge.py` cannot break the looper.
"""

import contextlib
import json
import os
import select
import sys
import termios
import tty
from typing import Any, Dict, Optional

DEFAULT_BAUD = 115200
CONFIG_NAME = "midi-bridge.json"
DEFAULT_CONFIG = os.path.join(
    os.path.expanduser("~"), ".config", "reduzent", CONFIG_NAME
)


def _config_candidates():
    """Ordered config paths to try: tools/config first, then user-level."""
    # Lives next to the tools so it survives regardless of launch directory.
    local = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config", CONFIG_NAME
    )
    return [local, DEFAULT_CONFIG]


def find_config(explicit=None):
    """Resolve which settings file to use.

    Priority: explicit --config path > tools/config/midi-bridge.json >
    ~/.config/reduzent/midi-bridge.json. The first existing file wins; if
    none exists yet, new settings are created at the explicit path (if given)
    or in the user config dir — never inside the repo by default.
    """
    if explicit:
        return explicit
    for cand in _config_candidates():
        if os.path.isfile(cand):
            return cand
    return DEFAULT_CONFIG


def midi_to_command(msg) -> Optional[str]:
    """Translate one mido message into a reduzent text command, or None.

    Pure function (no I/O) so it is unit-testable. `msg` is a mido.Message;
    the returned string has no trailing newline.
    """
    t = msg.type
    if t == "note_on":
        if msg.velocity > 0:
            return f"n {msg.channel} {msg.note} {msg.velocity}"
        return f"x {msg.channel} {msg.note}"
    if t == "note_off":
        return f"x {msg.channel} {msg.note}"
    if t == "pitchwheel":
        return f"p {msg.channel} {msg.pitch + 8192}"
    if t == "aftertouch":
        return f"a {msg.channel} {msg.value}"
    if t == "polytouch":
        return f"pa {msg.channel} {msg.note} {msg.value}"
    if t == "program_change":
        return f"g {msg.channel} {msg.program}"
    if t == "control_change":
        if msg.control == 1:
            return f"v {msg.channel} {msg.value}"
        if msg.control == 120:
            return f"panic {msg.channel}"
        if msg.control == 121:
            return f"resetcc {msg.channel}"
        if msg.control == 123:
            return f"noff {msg.channel}"
    return None


def load_settings(path: str) -> Dict[str, Any]:
    """Return the settings dict from `path`, or {} if missing/unreadable."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(path: str, settings: Dict[str, Any]) -> None:
    """Write `settings` as JSON, creating parent directories as needed."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)


def update_settings(path: str, values: Dict[str, Any]) -> None:
    """Merge `values` into the settings file at `path`, keeping other keys.

    Unlike save_settings this never drops keys it wasn't told about — port
    picks must not wipe channel names or hotkeys.
    """
    settings = load_settings(path)
    settings.update(values)
    save_settings(path, settings)


def resolve_settings(settings, midi_names, serial_names):
    """Return (midi_name, serial_port, baud) from saved settings.

    A saved port that is no longer detected falls back to the first available
    (or None). Pure, so it is unit-testable.
    """
    midi_name = settings.get("midi_input")
    if midi_name not in midi_names:
        midi_name = midi_names[0] if midi_names else None
    port = settings.get("serial_port")
    if port not in serial_names:
        port = serial_names[0] if serial_names else None
    try:
        baud = int(settings.get("baud", DEFAULT_BAUD))
    except (ValueError, TypeError):
        baud = DEFAULT_BAUD
    return midi_name, port, baud


def menu_choice(title, items, current):
    """Show a selectable list with arrow-key navigation.

    Up/Down arrows move the cursor, Enter selects, digits 1-9 jump to that
    item, and Escape accepts the default (last used). Ctrl-C raises
    KeyboardInterrupt.  Returns None when *items* is empty.
    """
    if not items:
        return None

    default_idx = items.index(current) if current in items else 0
    cursor = default_idx
    n = len(items)

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)

        # Print title then N placeholder lines, then rewind to the first.
        sys.stdout.write(f"{title}\r\n")
        for _ in range(n):
            sys.stdout.write("  \r\n")
        sys.stdout.write(f"\033[{n}A")
        sys.stdout.flush()

        while True:
            for i, item in enumerate(items):
                sys.stdout.write("\033[2K")  # clear line
                if i == cursor:
                    sys.stdout.write(f" \033[1;36m>\033[0m [{i + 1}] {item}")
                else:
                    sys.stdout.write(f"   [{i + 1}] {item}")
                if i == default_idx:
                    sys.stdout.write(" \033[2m(last used)\033[0m")
                sys.stdout.write("\r\n")
            sys.stdout.write(f"\033[{n}A")
            sys.stdout.flush()

            ch = os.read(fd, 1)
            if ch in (b"\r", b"\n"):
                return items[cursor]
            if ch == b"\x1b":
                # Escape — could be a bare Esc or arrow sequence (\x1b[A/B).
                if select.select([fd], [], [], 0.05)[0]:
                    seq = os.read(fd, 2)
                    if seq == b"[A":
                        cursor = (cursor - 1) % n
                    elif seq == b"[B":
                        cursor = (cursor + 1) % n
                else:
                    return items[default_idx]
            if ch == b"\x03":
                raise KeyboardInterrupt
            if ch.isdigit():
                idx = int(ch) - 1
                if 0 <= idx < n:
                    return items[idx]
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def select_ports(settings, midi_names, serial_names):
    """Prompt for MIDI input and serial port; return (midi_name, port, baud).

    Baud rate is read from *settings* (defaulting to DEFAULT_BAUD).  Use the
    `b` key at runtime to change it.
    """
    midi_name, port, baud = resolve_settings(settings, midi_names, serial_names)
    midi_name = menu_choice("MIDI input:", midi_names, midi_name)
    port = menu_choice("Serial port:", serial_names, port)
    return midi_name, port, baud


def open_connections(midi_name, port, baud):
    """Open the MIDI input and the serial output; return (inport, ser)."""
    import serial  # pyserial
    import mido
    return mido.open_input(midi_name), serial.Serial(port, baud, timeout=0)


def setup_scroll_region(bottom: int, top: int = 1) -> None:
    """Restrict scrolling to rows `top`..`rows-bottom` (1-based, inclusive).

    The lines above *top* stay fixed (used by the looper's channel column)
    and the *bottom* lines are reserved for the status bar.
    """
    rows = os.get_terminal_size().lines
    sys.stdout.write(f"\033[{top};{rows - bottom}r")
    sys.stdout.flush()


def reset_scroll_region() -> None:
    """Restore full terminal scroll region."""
    sys.stdout.write("\033[r")
    sys.stdout.flush()


@contextlib.contextmanager
def raw_terminal(fd):
    """Run in raw mode on `fd`; yield the previous termios attributes.

    On exit the previous settings are restored (TCSADRAIN). The yielded `old`
    lets the caller run `input()`-style prompts: temporarily restore `old`
    (termios.tcsetattr(fd, termios.TCSADRAIN, old)), run the prompt, then
    re-enter raw mode (tty.setraw(fd)).
    """
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    try:
        yield old
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
