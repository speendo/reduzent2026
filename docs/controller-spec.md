# Controller Firmware Spec

## Purpose

The central ESP32 controller receives live MIDI from a performer, maps each
message to an ESP-NOW event, and broadcasts it to the leaves (see
`docs/protocol-spec.md`). Before the MIDI controller is available, two dev-only
test sources (serial, autonomous) stand in for the MIDI input.

## Architecture

```
controller firmware
├── MIDI input (DIN → UART @31250)     ┐
├── serial source (dev-only)           ├→ event {type, channel, note, value}
├── autonomous source (dev-only)       ┘
├── ESP-NOW transmit (5-byte frame, broadcast)
├── serial command interface (settings trigger + test commands)
└── config (parasol)
```

There is no MAC mapping: events are broadcast and the leaf filters by channel
(byte 0 of the frame). The MIDI channel is forwarded verbatim as the frame's
channel byte.

## MIDI input (primary)

- DIN → UART at 31250 baud (assumed transport; USB-MIDI unresolved — backlog).
- Parser must handle **running status** and tolerate interleaved system
  real-time bytes (`0xF8`–`0xFF`).
- Forwarded subset (see `docs/research-notes.md`):
  - Note On / Note Off (`0x9n`/`0x8n`), velocity 0 = note off
  - Pitch Bend (`0xEn`, 14-bit)
  - Channel Aftertouch (`0xDn`) and Poly Aftertouch (`0xAn`)
  - Program Change (`0xCn`)
  - CC1 mod wheel (vibrato) and CC123/CC120/CC121 (panic)
- Each forwarded message becomes an event with the MIDI channel as its
  channel, serialized to the 5-byte frame.

## Test sources (dev-only)

- **Serial** — human-readable text commands, enabled in a test build:
  - `n <ch> <note> <vel>` note on · `x <ch> <note>` note off
  - `p <ch> <bend14>` pitch bend · `a <ch> <pressure>` channel aftertouch
  - `g <ch> <program>` program change · `v <ch> <depth>` vibrato (CC1)
  - `panic` all notes off
- **Autonomous** — a fixed looping demo pattern (and, optionally, a random
  stress mode) to validate the full path and timing.

## Serial command interface (not dev-only)

- `settings` — send `ENTER_SETTINGS` (broadcast or targeted) to leaves.
- `panic` — send `PANIC`.

## Event → ESP-NOW

- Events map 1:1 to the protocol frame (`channel, type, note, value, value hi`).
- Broadcast; fire-and-forget. See `docs/protocol-spec.md` and
  `docs/research-notes.md` for latency notes.

## Backlog

- USB-MIDI transport (4-byte packet framing) — pending hardware decision.
- Multiple controllers / MIDI emitters.
- MIDI-driven `ENTER_SETTINGS` trigger.
- Real-time clock sync (Start/Stop/Clock).
