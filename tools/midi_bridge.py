#!/usr/bin/env python3
"""MIDI -> serial bridge for the reduzent2026 controller.

Reads MIDI events from a MIDI input (keyboard, DAW, or virtual port) via mido
and writes reduzent text commands to the controller over serial. Forwards the
full MIDI subset (see docs/controller-spec.md): note on/off, pitch bend,
channel/poly aftertouch, program change, CC1 (vibrato), CC120/121/123 (panic).

Ports are chosen on start with a small interactive menu (MIDI input + serial
output); the last selection is remembered in a settings file so the menu can be
accepted by just pressing Enter next time. While running, press `m` to reopen
the menu and switch ports, `b` to change baud rate, `s` to send a leaf (or all)
into settings mode, or `q` (or Ctrl-C) to quit. Unix only (raw-terminal key
handling, like tools/keyboard-serial.py).

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

import os
import select
import sys
import termios
import threading
import tty
from typing import Optional

from reduzent_shared import (
    DEFAULT_CONFIG,
    find_config,
    load_settings,
    menu_choice,
    midi_to_command,
    open_connections,
    raw_terminal,
    reset_scroll_region,
    resolve_settings,
    save_settings,
    select_ports,
    setup_scroll_region,
)

_PROGRAM_NAMES = {0: "1-bit", 1: "arp", 2: "mono"}


def draw_status(midi_name: str, port: str, baud: int,
                override_ch: Optional[int], override_inst: Optional[int],
                last_channel: Optional[int] = None,
                last_program: Optional[int] = None,
                lock: Optional[threading.Lock] = None) -> None:
    """Redraw the two-line status bar at the terminal bottom."""
    rows = os.get_terminal_size().lines
    if override_ch is not None:
        ch_display = str(override_ch)
        ch_mode = "(override)"
    elif last_channel is not None:
        ch_display = str(last_channel)
        ch_mode = "(MIDI)"
    else:
        ch_display = "--"
        ch_mode = "(MIDI)"
    if override_inst is not None:
        inst_display = str(override_inst)
    elif last_program is not None:
        inst_display = _PROGRAM_NAMES.get(last_program, str(last_program))
    else:
        inst_display = "--"
    line1 = f" \033[1;36m\u25b8\033[0m USB MIDI Keyboard \u2192 \033[1;32m{port}\033[0m @ \033[1;32m{baud}\033[0m"
    line2 = (
        f" \033[1;36m\u25b8\033[0m ch: \033[1;32m{ch_display}\033[0m {ch_mode}  "
        f"inst: \033[1;32m{inst_display}\033[0m   "
        f"\033[2mm menu  b baud  s settings  c ch  i inst  p panic  o noff  q quit\033[0m"
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
    # Resolve once: --config flag > project config/ > user config dir.
    # All later loads AND saves go to this same file.
    config = find_config(config)

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
    try:
        midi_name, port, baud = select_ports(load_settings(config), midi_names, serial_names)
    except KeyboardInterrupt:
        return
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
    last_channel = None
    last_program = None

    def on_message(msg):
        nonlocal write_error
        nonlocal last_channel
        nonlocal last_program
        cmd = midi_to_command(msg)
        if cmd is None:
            return
        if msg.type in ("note_on", "note_off"):
            last_channel = msg.channel
        if msg.type == "program_change":
            last_program = msg.program
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
    with raw_terminal(fd) as old:

        last_redraw = 0
        serial_buf = ""
        sys.stdout.write("\033[2J\033[1;1H")
        sys.stdout.flush()
        setup_scroll_region(2)
        draw_status(midi_name, port, baud, override_ch, override_inst,
                    last_channel, last_program, stdout_lock)
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
                        draw_status(midi_name, port, baud, override_ch, override_inst,
                                    last_channel, last_program, stdout_lock)
                        last_redraw = now
                    continue
                ch = sys.stdin.read(1)
                if ch in ("\x03", "q", "Q"):
                    reset_scroll_region()
                    break
                if ch in ("m", "M"):
                    # Restore canonical mode so the menu's input() works.
                    # Disable MIDI callback so messages don't corrupt the menu display.
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    inport.callback = None
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
                                inport.close()
                                inport, ser = new_inport, new_ser
                                with lock:
                                    state["ser"] = ser
                                midi_name, port, baud = new_midi, new_port, new_baud
                                save_settings(config, {
                                    "midi_input": midi_name,
                                    "serial_port": port,
                                    "baud": baud,
                                })
                    finally:
                        inport.callback = on_message
                        tty.setraw(fd)
                    draw_status(midi_name, port, baud, override_ch, override_inst,
                                last_channel, last_program, stdout_lock)
                if ch in ("s", "S"):
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    inport.callback = None
                    try:
                        target = input("Settings mode for leaf id [all]: ").strip()
                    finally:
                        inport.callback = on_message
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
                    draw_status(midi_name, port, baud, override_ch, override_inst,
                                last_channel, last_program, stdout_lock)
                if ch in ("c", "C"):
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    inport.callback = None
                    try:
                        raw = input("Channel [0-15, empty=reset]: ").strip()
                    finally:
                        inport.callback = on_message
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
                    draw_status(midi_name, port, baud, override_ch, override_inst,
                                last_channel, last_program, stdout_lock)
                if ch in ("i", "I"):
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    inport.callback = None
                    try:
                        raw = input("Instrument [0-127, empty=reset]: ").strip()
                    finally:
                        inport.callback = on_message
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
                    draw_status(midi_name, port, baud, override_ch, override_inst,
                                last_channel, last_program, stdout_lock)
                if ch in ("p", "P"):
                    with lock:
                        s = state["ser"]
                        if s is not None:
                            s.write(b"panic\n")
                if ch in ("o", "O"):
                    target = override_ch if override_ch is not None else last_channel
                    if target is None:
                        with stdout_lock:
                            sys.stdout.write("no active channel to silence\r\n")
                            sys.stdout.flush()
                    else:
                        with lock:
                            s = state["ser"]
                            if s is not None:
                                s.write(f"noff {target}\n".encode())
                if ch in ("b", "B"):
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    inport.callback = None
                    try:
                        raw = input(f"Baud rate [{baud}]: ").strip()
                    finally:
                        inport.callback = on_message
                        tty.setraw(fd)
                    if raw:
                        try:
                            new_baud = int(raw)
                            if new_baud > 0:
                                with lock:
                                    state["ser"] = None
                                    ser.close()
                                try:
                                    ser = serial.Serial(port, new_baud, timeout=0)
                                except OSError:
                                    print(f"could not open {port} at {new_baud}")
                                    ser = serial.Serial(port, baud, timeout=0)
                                else:
                                    baud = new_baud
                                    save_settings(config, {
                                        "midi_input": midi_name,
                                        "serial_port": port,
                                        "baud": baud,
                                    })
                                with lock:
                                    state["ser"] = ser
                            else:
                                print("baud rate must be positive")
                        except ValueError:
                            print("invalid input")
                    draw_status(midi_name, port, baud, override_ch, override_inst,
                                last_channel, last_program, stdout_lock)
        except KeyboardInterrupt:
            pass
        finally:
            inport.callback = None
            with lock:
                s = state["ser"]
                if s is not None:
                    for _ in range(3):
                        s.write(b"panic\n")
            with lock:
                state["ser"] = None
                ser.close()
            inport.close()
            reset_scroll_region()
            # Clear screen and restore cursor to top-left on exit
            sys.stdout.write("\033[2J\033[1;1H")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
