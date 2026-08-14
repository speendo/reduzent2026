# Controller Firmware Spec

## Purpose

The central ESP32 controller receives input from a computer over serial —
either human-typed text commands or raw MIDI bytes — and broadcasts it to the
leaves as ESP-NOW events. A real MIDI keyboard is connected through a computer
acting as a proxy (MIDI → serial); a keyboard plugged directly into the
controller (USB-MIDI host) is backlog.

## Architecture

```
controller firmware
├── serial input (UART / USB-serial)        ┐
│   ├── text commands (manual / scripted)   ├→ event {type, channel, note, value}
│   └── raw MIDI bytes (computer proxy)     ┘
├── autonomous source (dev-only)            ┘
├── ESP-NOW transmit (5-byte frame, broadcast)
├── serial command interface (text + settings/panic)
└── config (parasol)
```

No MAC mapping: events are broadcast and the leaf filters by channel (byte 0 of
the frame). The MIDI channel (or the channel given in a text command) is
forwarded verbatim as the frame's channel byte.

## Serial input (primary)

- One serial link (UART / USB-serial). The byte stream is either text commands
  or raw MIDI bytes, distinguished by the first byte (`>= 0x80` = MIDI status,
  otherwise text).
- **Text commands** — step 1, human-typed or scripted:
  - `n <ch> <note> <vel>` note on · `x <ch> <note>` note off
  - `p <ch> <bend>` pitch bend (0–16383) · `a <ch> <pressure>` channel aftertouch
  - `pa <ch> <note> <pressure>` poly aftertouch · `g <ch> <program>` program change
  - `v <ch> <depth>` vibrato (CC1) · `panic` all notes off · `settings` enter settings
- **Raw MIDI bytes** — step 2 (computer proxy): the computer sends standard MIDI
  bytes over serial at the link baud (31250 is DIN-only, not used here).
- Real-time keyboard testing (no Enter): `tools/keyboard-serial.py` sends a
  note-on/off blip per keypress.

## MIDI parser

- Handles **running status** and tolerates interleaved system real-time bytes
  (`0xF8`–`0xFF`).
- Forwarded subset (see `docs/research-notes.md`):
  - Note On / Note Off (`0x9n`/`0x8n`), velocity 0 = note off
  - Pitch Bend (`0xEn`, 14-bit)
  - Channel Aftertouch (`0xDn`) and Poly Aftertouch (`0xAn`)
  - Program Change (`0xCn`)
  - CC1 mod wheel (vibrato) and CC123/CC120/CC121 (panic)
- Each message becomes an event with the MIDI channel as its channel.

## Autonomous source (dev-only)

- A fixed looping demo pattern (and, optionally, a random stress mode) to
  validate the full path and timing without a computer attached.

## Event → ESP-NOW

- Events map 1:1 to the protocol frame (`channel, type, note, value, value hi`).
- Broadcast; fire-and-forget. See `docs/protocol-spec.md` and
  `docs/research-notes.md` for latency notes.

## Backlog

- USB-MIDI host (MIDI keyboard plugged directly into the controller) — no
  hardware decision yet (S3 vs USB host shield vs classic+proxy).
- DIN → UART @31250 input.
- Multiple controllers / MIDI emitters.
- MIDI-driven `ENTER_SETTINGS` trigger.
- Real-time clock sync (Start/Stop/Clock).
