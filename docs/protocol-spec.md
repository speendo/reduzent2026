# ESP-NOW Protocol Spec

## Purpose

Compact event relay from the controller to 12 leaves (6 piezo, 6 solenoid).
Carries the agreed MIDI subset plus a settings-mode command. Low latency and
fire-and-forget — no acknowledgements.

## Transport

- ESP-NOW broadcast; fire-and-forget (no acks/retries).
- Channel-first frame so a leaf filters on byte 0 and bails immediately.
- All devices share one WiFi channel (ESP-NOW requirement), fixed at build time.

## Frame (fixed 5 bytes)

| byte | field    | meaning                                      |
|------|----------|----------------------------------------------|
| 0    | channel  | target node 0–15, or `0xFF` = all leaves     |
| 1    | type     | event type (see below)                       |
| 2    | note     | note number (NOTE, POLY_AFTERTOUCH only)     |
| 3    | value    | velocity / pressure / program / depth / pitch-bend LSB |
| 4    | value hi | pitch-bend MSB only                          |

## Event types

| type                | channel     | note | value               | leaf action                                   |
|---------------------|-------------|------|---------------------|-----------------------------------------------|
| NOTE                | target      | yes  | velocity (0 = off)  | piezo: play/stop note; solenoid: strike       |
| PITCH_BEND          | target      | —    | 14-bit bend         | piezo: bend active notes                      |
| CHANNEL_AFTERTOUCH  | target      | —    | pressure            | piezo: amplitude modulation                   |
| POLY_AFTERTOUCH     | target      | yes  | pressure            | piezo: per-note amplitude                     |
| PROGRAM_CHANGE      | target      | —    | program             | piezo: select mode (0 = arpeggio, 1 = 1-bit)  |
| CC1_VIBRATO         | target      | —    | depth               | piezo: vibrato depth                          |
| PANIC               | 0xFF        | —    | —                   | all leaves: stop everything                   |
| ENTER_SETTINGS      | 0xFF        | id  | —                   | enter settings mode; note = leaf id (0–254), 0xFF = all |

## Addressing & mapping

- byte 0 is the routing key: leaf keeps its own channel (from parasol config)
  and accepts frames where `channel == MY_CHANNEL || channel == 0xFF`.
- No MAC table, no pairing — the controller broadcasts, leaves filter.
- MIDI channel → node: each leaf is assigned a channel via parasol.
- Each leaf also has a unique **node id** (0–254, parasol), distinct from its
  channel and used only to address a single leaf (e.g. `ENTER_SETTINGS`).
  Channels are shared (solenoids), so a channel alone does not identify a leaf.

## Note → frequency

- The controller forwards the note *number*; the piezo leaf converts it to Hz
  (`f = 440 · 2^((n-69)/12)`).
- Piezo: note → frequency, velocity → amplitude (LEDC duty).
- Solenoid: one shared channel, note selects which solenoid, velocity →
  intensity (PWM duty via lookup table).

## Polyphony (piezo leaf)

- Leaf tracks active notes via NOTE on/off (velocity 0 = off), up to
  `MAX_VOICES` (8).
- Overflow: steal the quietest/oldest voice (leaf-spec detail).

## Latency

- Fire-and-forget keeps end-to-end ~1–5 ms; frame size is not the driver
  (channel contention is). See docs/research-notes.md.

## Backlog

- Unicast with static MAC table; auto-discovery/pairing.
- Acks/retries (only if drops are observed).
- Multiple controllers; encryption.
- Multi-channel actuators (a leaf on several channels).
