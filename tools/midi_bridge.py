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
    pip install -r tools/requirements.txt
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
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
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
    try:
        baud = int(settings.get("baud", DEFAULT_BAUD))
    except (ValueError, TypeError):
        baud = DEFAULT_BAUD
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


def setup_scroll_region(bottom: int) -> None:
    """Reserve `bottom` lines at the terminal bottom for the status bar."""
    rows = os.get_terminal_size().lines
    sys.stdout.write(f"\033[1;{rows - bottom}r")
    sys.stdout.flush()


def reset_scroll_region() -> None:
    """Restore full terminal scroll region."""
    sys.stdout.write("\033[r")
    sys.stdout.flush()


def draw_status(midi_name: str, port: str, baud: int,
                override_ch: Optional[int], override_inst: Optional[int],
                lock: Optional[threading.Lock] = None) -> None:
    """Redraw the two-line status bar at the terminal bottom."""
    rows = os.get_terminal_size().lines
    ch_display = str(override_ch) if override_ch is not None else "0"
    ch_mode = "(override)" if override_ch is not None else "(MIDI)"
    inst_display = str(override_inst) if override_inst is not None else "--"
    line1 = f" \033[1;36m\u25b8\033[0m USB MIDI Keyboard \u2192 \033[1;32m{port}\033[0m @ \033[1;32m{baud}\033[0m"
    line2 = (
        f" \033[1;36m\u25b8\033[0m ch: \033[1;32m{ch_display}\033[0m {ch_mode}  "
        f"inst: \033[1;32m{inst_display}\033[0m   "
        f"\033[2mm menu  s settings  c ch  i inst  q quit\033[0m"
    )
    ctx = lock if lock else _noop_ctx()
    with ctx:
        sys.stdout.write("\033[s")  # save cursor
        sys.stdout.write(f"\033[{rows - 1};1H\033[2K{line1}")
        sys.stdout.write(f"\033[{rows};1H\033[2K{line2}")
        sys.stdout.write("\033[u")  # restore cursor
        sys.stdout.flush()


class _noop_ctx:
    """Null context manager for when no lock is provided."""
    def __enter__(self):
        return self
    def __exit__(self, *a):
        pass


def main() -> None:
    import serial
    import serial.tools.list_ports
    import time
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
    stdout_lock = threading.Lock()
    state = {"ser": ser}
    write_error = False
    override_ch = None
    override_inst = None

    def on_message(msg):
        nonlocal write_error
        cmd = midi_to_command(msg)
        if cmd is None:
            return
        if override_ch is not None or override_inst is not None:
            parts = cmd.split()
            if override_ch is not None:
                if parts[0] in ("n", "x", "p", "a", "g", "v") and len(parts) >= 2:
                    parts[1] = str(override_ch)
                elif parts[0] == "pa" and len(parts) >= 3:
                    parts[1] = str(override_ch)
            if override_inst is not None and parts[0] == "g" and len(parts) >= 3:
                parts[2] = str(override_inst)
            cmd = " ".join(parts)
        with lock:
            s = state["ser"]
            if s is not None:
                try:
                    s.write((cmd + "\n").encode())
                except OSError:
                    if not write_error:
                        write_error = True
                        with stdout_lock:
                            sys.stdout.write("serial write failed; will retry\r\n")
                            sys.stdout.flush()
                    try:
                        state["ser"] = None
                        s.close()
                    except OSError:
                        pass
        if not quiet:
            with stdout_lock:
                sys.stdout.write(cmd + "\r\n")
                sys.stdout.flush()

    inport.callback = on_message

    # Raw stdin so a single keypress is detected without Enter (Unix only).
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)

    last_redraw = 0
    serial_buf = ""
    setup_scroll_region(2)
    draw_status(midi_name, port, baud, override_ch, override_inst, stdout_lock)
    try:
        while True:
            # Echo whatever the controller writes back (tx / send failed / hb).
            with lock:
                s = state["ser"]
                if s is not None:
                    try:
                        data = s.read(256)
                    except OSError:
                        data = b""
                    if data:
                        serial_buf += data.decode("utf-8", errors="replace")
                        # Write only complete lines (ending with \n).
                        # Partial lines stay in the buffer until next read.
                        while "\n" in serial_buf:
                            line, serial_buf = serial_buf.split("\n", 1)
                            # Raw mode needs \r\n; controller sends \n only
                            out = line + "\r\n"
                            if out.startswith("hb "):
                                out = f"\033[2;36m{out}\033[0m"
                            with stdout_lock:
                                sys.stdout.write(out)
                                sys.stdout.flush()

            # Auto-reopen the serial port after a dropped connection.
            if state["ser"] is None:
                try:
                    new_ser = serial.Serial(port, baud, timeout=0)
                except OSError:
                    pass
                else:
                    with lock:
                        state["ser"] = new_ser
                    write_error = False
                    with stdout_lock:
                        sys.stdout.write(f"reconnected to {port}\r\n")
                        sys.stdout.flush()

            if not select.select([sys.stdin], [], [], 0.1)[0]:
                now = time.monotonic()
                if now - last_redraw >= 2.0:
                    draw_status(midi_name, port, baud, override_ch, override_inst, stdout_lock)
                    last_redraw = now
                continue
            ch = sys.stdin.read(1)
            if ch in ("\x03", "q", "Q"):
                reset_scroll_region()
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
                        try:
                            new_inport, new_ser = open_connections(new_midi, new_port, new_baud)
                        except OSError:
                            print("could not open new ports; keeping current connection")
                        else:
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
                            draw_status(midi_name, port, baud, override_ch, override_inst, stdout_lock)
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
                draw_status(midi_name, port, baud, override_ch, override_inst, stdout_lock)
            if ch in ("c", "C"):
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                try:
                    raw = input("Channel [0-15, empty=reset]: ").strip()
                finally:
                    tty.setraw(fd)
                if raw:
                    try:
                        val = int(raw)
                        if 0 <= val <= 15:
                            override_ch = val
                        else:
                            print("channel must be 0-15")
                    except ValueError:
                        print("invalid input")
                else:
                    override_ch = None
                draw_status(midi_name, port, baud, override_ch, override_inst, stdout_lock)
            if ch in ("i", "I"):
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                try:
                    raw = input("Instrument [0-127, empty=reset]: ").strip()
                finally:
                    tty.setraw(fd)
                if raw:
                    try:
                        val = int(raw)
                        if 0 <= val <= 127:
                            override_inst = val
                            # Send program change immediately to all leaves
                            with lock:
                                s = state["ser"]
                                if s is not None:
                                    s.write(f"g {override_ch if override_ch is not None else 0} {override_inst}\n".encode())
                        else:
                            print("program must be 0-127")
                    except ValueError:
                        print("invalid input")
                else:
                    override_inst = None
                draw_status(midi_name, port, baud, override_ch, override_inst, stdout_lock)
    except KeyboardInterrupt:
        pass
    finally:
        inport.callback = None
        with lock:
            state["ser"] = None
            ser.close()
        inport.close()
        reset_scroll_region()
        # Clear screen and restore cursor to top-left on exit
        sys.stdout.write("\033[2J\033[1;1H")
        sys.stdout.flush()
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
