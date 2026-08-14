#!/usr/bin/env python3
"""Test keyboard -> serial for the reduzent2026 controller.

Reads the computer keyboard in raw mode (no Enter needed) and sends
`n <ch> <note> <vel>` / `x <ch> <note>` text commands to the controller over
serial. Each key press is a short "blip": note-on followed by note-off after
BLIP_MS. Test-only; not part of the product.

Usage:
    pip install pyserial
    python3 tools/keyboard-serial.py /dev/ttyUSB0 [115200]

Quit with Ctrl-C.
"""

import select
import sys
import termios
import time
import tty

import serial

# Computer key -> (channel, note). Piano-style layout.
KEYS = {
    "a": (0, 60),  # C4
    "w": (0, 61),
    "s": (0, 62),
    "e": (0, 63),
    "d": (0, 64),
    "f": (0, 65),
    "t": (0, 66),
    "g": (0, 67),
    "y": (0, 68),
    "h": (0, 69),
    "u": (0, 70),
    "j": (0, 71),
    "k": (0, 72),
}

VELOCITY = 100
BLIP_MS = 120


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    port = sys.argv[1]
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

    ser = serial.Serial(port, baud, timeout=0)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)

    print(f"keys: {' '.join(KEYS)}  (Ctrl-C to quit)")
    try:
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not ready:
                continue
            key = sys.stdin.read(1)
            if key == "\x03":  # Ctrl-C
                break
            if key not in KEYS:
                continue
            ch, note = KEYS[key]
            ser.write(f"n {ch} {note} {VELOCITY}\n".encode())
            time.sleep(BLIP_MS / 1000)
            ser.write(f"x {ch} {note}\n".encode())
            print(key, end="", flush=True)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        ser.close()


if __name__ == "__main__":
    main()
