#!/usr/bin/env python3
"""MIDI -> serial bridge for the reduzent2026 controller.

Reads MIDI events from a MIDI input (keyboard, DAW, or virtual port) via mido
and writes reduzent text commands to the controller over serial. Forwards the
full MIDI subset (see docs/controller-spec.md): note on/off, pitch bend,
channel/poly aftertouch, program change, CC1 (vibrato), CC120/121/123 (panic).

Ports are chosen on start with a small interactive menu (MIDI input + serial
output); the last selection is remembered in a settings file so the menu can be
accepted by just pressing Enter next time. While running, press `m` to reopen
the menu and switch ports, `s` to send a leaf (or all) into settings mode, or `q`
(or Ctrl-C) to quit. Unix only (raw-terminal key handling, like
tools/keyboard-serial.py).

MIDI is delivered through mido's native callback (a background thread that
blocks in the driver and fires on message arrival), so forwarding is
event-driven: no polling, minimal added latency, ~zero CPU when idle. Pass
`--quiet` to skip the per-message console log on latency-critical runs.

Usage:
    pip install mido python-rtmidi pyserial
    python3 tools/midi_bridge.py                 # interactive menu
    python3 tools/midi_bridge.py --list          # list ports and exit
    python3 tools/midi_bridge.py --config PATH   # use PATH as settings file
    python3 tools/midi_bridge.py --quiet         # no per-message log (latency)

Quit with Ctrl-C (or `q`).
"""

import json
import os
import select
import sys
import termios
import threading
import tty
from typing import Any, Dict, Optional

DEFAULT_BAUD = 115200
DEFAULT_CONFIG = os.path.join(
    os.path.expanduser("~"), ".config", "reduzent", "midi-bridge.json"
)


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
        if msg.control in (120, 121, 123):
            return "panic"
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(settings, f, indent=2)


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
    baud = int(settings.get("baud", DEFAULT_BAUD))
    return midi_name, port, baud


def menu_choice(title, items, current):
    """Print a numbered list (marking `current`) and return the chosen item.

    Enter accepts `current`; a number picks that item; anything invalid falls
    back to `current`. Returns None when `items` is empty.
    """
    print(title)
    default_idx = items.index(current) if current in items else 0
    for i, item in enumerate(items):
        mark = "  (last used)" if i == default_idx else ""
        print(f"  [{i + 1}] {item}{mark}")
    if not items:
        return None
    raw = input("> ").strip()
    if not raw:
        return items[default_idx]
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(items):
            return items[idx]
    except ValueError:
        pass
    return items[default_idx]


def select_ports(settings, midi_names, serial_names):
    """Prompt for MIDI input, serial port, and baud; return the triple."""
    midi_name, port, baud = resolve_settings(settings, midi_names, serial_names)
    midi_name = menu_choice("MIDI input:", midi_names, midi_name)
    port = menu_choice("Serial port:", serial_names, port)
    raw = input(f"Baud rate [{baud}]: ").strip()
    if raw:
        try:
            baud = int(raw)
        except ValueError:
            pass
    return midi_name, port, baud


def open_connections(midi_name, port, baud):
    """Open the MIDI input and the serial output; return (inport, ser)."""
    import serial  # pyserial
    import mido
    return mido.open_input(midi_name), serial.Serial(port, baud, timeout=0)


def main() -> None:
    import serial.tools.list_ports
    import mido

    argv = sys.argv[1:]
    config = DEFAULT_CONFIG
    quiet = "--quiet" in argv
    for i, a in enumerate(argv):
        if a == "--config" and i + 1 < len(argv):
            config = argv[i + 1]

    def detected():
        return (
            mido.get_input_names(),
            [p.device for p in serial.tools.list_ports.comports()],
        )

    if "--list" in argv:
        print("MIDI inputs:")
        for n in mido.get_input_names():
            print(f"  - {n}")
        print("Serial ports:")
        for p in serial.tools.list_ports.comports():
            print(f"  - {p.device} - {p.description}")
        return

    midi_names, serial_names = detected()
    midi_name, port, baud = select_ports(load_settings(config), midi_names, serial_names)
    if midi_name is None or port is None:
        raise SystemExit("no MIDI input or serial port detected")
    inport, ser = open_connections(midi_name, port, baud)
    save_settings(config, {"midi_input": midi_name, "serial_port": port, "baud": baud})

    # MIDI arrives via mido's native callback (a background thread that blocks
    # in the driver and fires on arrival) — event-driven, no polling. `state`
    # holds the live serial port so the `m` key can swap it without racing the
    # callback thread.
    lock = threading.Lock()
    state = {"ser": ser}

    def on_message(msg):
        cmd = midi_to_command(msg)
        if cmd is None:
            return
        with lock:
            s = state["ser"]
            if s is not None:
                s.write((cmd + "\n").encode())
        if not quiet:
            print(cmd, flush=True)

    inport.callback = on_message

    # Raw stdin so a single keypress is detected without Enter (Unix only).
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)

    print(f"bridging {inport.name} -> {port} @ {baud}  (m = menu, s = settings, q = quit)")
    try:
        while True:
            if not select.select([sys.stdin], [], [], 0.1)[0]:
                continue
            ch = sys.stdin.read(1)
            if ch in ("\x03", "q", "Q"):
                break
            if ch in ("m", "M"):
                # Restore canonical mode so the menu's input() works.
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                try:
                    midi_names, serial_names = detected()
                    new_midi, new_port, new_baud = select_ports(
                        load_settings(config), midi_names, serial_names
                    )
                    if new_midi is None or new_port is None:
                        print("no ports detected; keeping current connection")
                    else:
                        new_inport, new_ser = open_connections(new_midi, new_port, new_baud)
                        with lock:
                            state["ser"] = None
                            ser.close()
                        inport.callback = None
                        inport.close()
                        inport, ser = new_inport, new_ser
                        with lock:
                            state["ser"] = ser
                        inport.callback = on_message
                        midi_name, port, baud = new_midi, new_port, new_baud
                        save_settings(config, {
                            "midi_input": midi_name,
                            "serial_port": port,
                            "baud": baud,
                        })
                        print(f"bridging {inport.name} -> {port} @ {baud}")
                finally:
                    tty.setraw(fd)
            if ch in ("s", "S"):
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                try:
                    target = input("Settings mode for leaf id [all]: ").strip()
                finally:
                    tty.setraw(fd)
                cmd = "settings\n"
                if target:
                    try:
                        int(target)
                        cmd = f"settings {target}\n"
                    except ValueError:
                        cmd = "settings\n"
                with lock:
                    s = state["ser"]
                    if s is not None:
                        s.write(cmd.encode())
                if not quiet:
                    print("settings", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        inport.callback = None
        with lock:
            state["ser"] = None
            ser.close()
        inport.close()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
