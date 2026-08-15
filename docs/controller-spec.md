# Controller Firmware Spec

## Purpose

The central ESP32 controller receives text commands from a computer over serial
(human-typed, scripted, or emitted by the MIDI bridge) and broadcasts them to the
leaves as ESP-NOW events. MIDI parsing lives on the computer bridge: a real MIDI
keyboard is connected through a computer (MIDI → text commands), not directly to
the controller; a keyboard plugged directly into the controller (USB-MIDI host)
is backlog.

## Architecture

```
controller firmware
├── serial input (UART / USB-serial)        ┐
│   └── text commands (manual / scripted / MIDI bridge)  ├→ event {type, channel, note, value}  ┘
├── ESP-NOW transmit (5-byte frame, broadcast)
├── ESP-NOW receive → heartbeat log (hb <mac> played=N last=Ns)
├── serial command interface (text + settings/panic)
└── config (parasol)
```

No MAC mapping: events are broadcast and the leaf filters by channel (byte 0 of
the frame). The MIDI channel (or the channel given in a text command) is
forwarded verbatim as the frame's channel byte.

## Serial input (primary)

- One serial link (UART / USB-serial). The controller receives text commands
  (human-typed, scripted, or emitted by the MIDI bridge).
- **Text commands** — human-typed or scripted:
  - `n <ch> <note> <vel>` note on · `x <ch> <note>` note off
  - `p <ch> <bend>` pitch bend (0–16383) · `a <ch> <pressure>` channel aftertouch
  - `pa <ch> <note> <pressure>` poly aftertouch · `g <ch> <program>` program change
  - `v <ch> <depth>` vibrato (CC1) · `panic` all notes off · `settings` enter settings
- **MIDI bridge** — a real MIDI keyboard/DAW is connected to a computer, and
  `tools/midi_bridge.py` (mido) parses the MIDI stream and emits the text
  commands above over serial. MIDI parsing lives on the computer, not the
  controller (a MIDI keyboard cannot plug into the ESP32 directly; USB-MIDI
  host is backlog).
- Real-time keyboard testing (no Enter): `tools/keyboard-serial.py` sends a
  note-on/off blip per keypress.

## MIDI parsing

- Handled by `tools/midi_bridge.py` (mido + python-rtmidi), which copes with
  running status, interleaved system real-time bytes, and SysEx, and forwards
  the subset below as text commands:
  - Note On / Note Off (`0x9n`/`0x8n`), velocity 0 = note off
  - Pitch Bend (`0xEn`, 14-bit)
  - Channel Aftertouch (`0xDn`) and Poly Aftertouch (`0xAn`)
  - Program Change (`0xCn`)
  - CC1 mod wheel (vibrato) and CC123/CC120/CC121 (panic)

## Event → ESP-NOW

- Events map 1:1 to the protocol frame (`channel, type, note, value, value hi`).
- Broadcast; fire-and-forget. See `docs/protocol-spec.md` and
  `docs/research-notes.md` for latency notes.

## Backlog

- Demo/standalone mode (autonomous source) — self-playing pattern without a
  computer attached.
- USB-MIDI host (MIDI keyboard plugged directly into the controller) — no
  hardware decision yet (S3 vs USB host shield vs classic+proxy).
- DIN → UART @31250 input.
- Multiple controllers / MIDI emitters.
- MIDI-driven `ENTER_SETTINGS` trigger (currently triggered by the bridge `s` key / text command).
- Real-time clock sync (Start/Stop/Clock).
- Raw MIDI bytes over serial (parse MIDI on the controller) — only needed for
  a DIN → UART @31250 direct input with no computer; the computer bridge
  currently parses MIDI.
- Left/right pan mapping (low notes → left leaves, high notes → right): a
  spatialization effect tied to the 12-leaf layout; a natural bridge-side
  feature to discuss when planning the 12-leaf build.
- Event-driven serial receive: replace the controller `loop()`'s `delay(1)`
  polling with a UART/USB-CDC receive callback so it idles *and* reacts
  immediately (drops the ~1 ms polling granularity). Board-dependent: classic
  ESP32 → `Serial.onReceive(cb)`; ESP32-C3 (USB CDC) → `Serial.onEvent(ARDUINO_HW_CDC_RX_EVENT, cb)`.
- Reopen the serial port on read failure too: a read-side `OSError` currently
  swallows the error and returns empty data without marking the port for
  reopen, so recovery only triggers on a write failure. A cable pull while no
  MIDI is flowing would otherwise never reconnect.
