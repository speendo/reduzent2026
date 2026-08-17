# Research notes & decisions

Record of technical decisions made during the pre-implementation research and
brainstorming, so rationale is not lost. Written 2026-08-14.

## 1. Audio / PWM output for piezo (ESP32-C3)

**Decision: native LEDC PWM at the note frequency + software amplitude envelope.**

- ESP32-C3 has no DAC; PWM is the native way to drive a bare piezo at a note
  frequency.
- LEDC: 6 channels, 4 timers, low-speed mode only. At the 80 MHz APB clock,
  musical notes (27 Hz – 4 kHz) leave >12-bit duty resolution — enough for
  7-bit velocity.
- `ledc_set_freq()` retunes on the fly (for different notes / arpeggio).
- Hardware fade (`ledc_set_fade_with_time`) can drive the ADSR amplitude
  envelope — no timer ISR needed.
- Gotcha: at max duty resolution, writing `duty == 2^res` overflows the
  hardware counter; clamp to `2^res - 1`.

**Rejected (backlog):**

- *Mozzi* — continuous-synthesis engine (fixed-rate audio ISR). Overkill for
  "note + decay", competes with ESP-NOW on the single-core C3, LGPL relinking
  obligations. Backlog if richer synthesis is ever wanted.
- *ESP32Synth* (danilogcrf2-oss) — good polyphonic engine (MIT, supports C3 via
  `SMODE_PWM`), but `SMODE_PWM` outputs a ~48 kHz carrier expecting an RC
  low-pass filter (a speaker/DAC path, wrong for a bare piezo), runs a
  continuous 48 kHz synthesis ISR, and needs 160 MHz. Backlog.

## 2. MIDI essentials

**Decision: parse a minimal MIDI subset and forward it as compact events.**

Use (MVP):

- Note On (`0x9n`, note, velocity); velocity 0 == note off.
- Note Off (`0x8n`, note, velocity) — triggers release; release-velocity value
  ignored for MVP.
- Channel (in status byte) → node routing.
- Note number → piezo frequency / solenoid select.
- Pitch Bend (`0xEn`, 14-bit) → piezo frequency bend.
- Channel Aftertouch (`0xDn`) and Poly Aftertouch (`0xAn`) → piezo amplitude.
- Program Change (`0xCn`) → minimal mode select (arpeggio vs 1-bit mixing).
- CC1 (mod wheel) → vibrato depth (piezo).
- CC123 All Notes Off (+ CC120 All Sound Off, CC121 Reset) → panic / stuck-note
  recovery.

Skip (MVP): sustain CC64 (unless a pedal appears), other CCs, SysEx, Song
Select/Position, Tune Request.

Tolerate/ignore: Active Sensing (`0xFE`), System Reset (`0xFF`), system
real-time (`0xF8`–`0xFF` interleaved).

Non-negotiable parsing rules:

- Running status (omitted status byte) is common in real streams — must handle.
- Real-time bytes can appear mid-message — skip without corrupting state.

## 3. ESP-NOW protocol direction

**Decision: compact typed event relay** `{type, channel, note, value}`.

Types: `NOTE`, `PITCH_BEND`, `CHANNEL_AFTERTOUCH`, `POLY_AFTERTOUCH`,
`PROGRAM_CHANGE`, `CC`, `PANIC`, `ENTER_SETTINGS`.

Pitch bend needs a 14-bit value (2 bytes); poly aftertouch needs a note field.
Frames stay ~6 bytes.

Latency: payload size is not the driver (3 → 7 bytes costs ~30 µs on air);
channel contention and retries dominate. **Fire-and-forget (no acks)** is the
single most important latency decision. End-to-end target ~1–5 ms.

Reliability (2026-08-17): the fire-and-forget link drops frames, and a dropped
note-off leaves a note stuck in SUSTAIN. Resolution: a controller keepalive
(`NOTE_HOLD` every 750 ms) plus a leaf watchdog that releases a SUSTAIN voice
not refreshed within 3 s. Panic is hard-stop, `NOTES_OFF` is release; both are
channel-scoped and sent redundantly. MIDI CC120/121/123 map to hard-stop /
reset-controllers / release respectively. See
`docs/superpowers/specs/2026-08-17-espnow-reliability-design.md`.

## 4. Polyphony (piezo)

**Decision: simulated ADSR + polyphony via two runtime-selectable modes.**

- ADSR: LEDC duty = amplitude; attack/decay/release via hardware fade, sustain
  = held duty.
- Arpeggio: retune LEDC frequency across the chord notes at ~30–60 Hz. Cheap.
- 1-bit digital mixing: combine N square waves (XOR / weighted) into one 1-bit
  stream via a timer ISR or the sigma-delta (SDM) peripheral. Feasible, but a
  continuous ISR on the single core competes with ESP-NOW — defer if it causes
  latency problems.
- Mode selection: runtime parasol setting (also addressable via Program Change,
  minimal).
- Polyphony depth: fixed `MAX_VOICES = 8` compile constant, no runtime setting.
  Cost scales with *active* voices, not the ceiling. ~4 notes is the
  musical/quality sweet spot; 8 is headroom.
- Voice stealing on overflow: policy TBD (rec: steal quietest/oldest).

## 5. Solenoid velocity

**Decision: PWM duty-cycle current control** (LEDC, fixed ~20–25 kHz, duty ∝
velocity).

Why: solenoid strike force is proportional to coil current; PWM duty sets
average current via the coil's inductance.

- 20 kHz → ~12-bit duty resolution, plenty for 7-bit velocity.
- One LEDC channel + one timer per solenoid leaf; fixed frequency, so no
  conflict with the piezo's variable frequency.
- Needs a flyback diode across the coil (standard with MOSFET drive; confirm on
  board).
- Velocity→duty is not perfectly linear; use a lookup table (calibrate on
  hardware).
- Strike envelope: energize at duty D for ~30–50 ms then off; note-off ignored
  (percussive).
- Power: at high duty the 12 V step-up + Li-ion must supply the surge; watch
  for sag during bring-up.

**Rejected (recorded so we don't reconsider it later):** on-time / pulse-width
control — energize at 100% for a duration ∝ velocity. Once the plunger
completes its pull-in travel, extra time adds no force, so this gives only a
coarse "tap vs full" (2–3 steps), not a smooth velocity curve.

## 6. Settings / live mode

**Decision: two modes per device.**

- Live = default, no WiFi, low latency.
- Settings = parasol web UI, entered briefly after boot, or when the controller
  signals it.
- `ENTER_SETTINGS` is a native ESP-NOW event type — not repurposed MIDI (the
  leaf is not a MIDI device).
- Trigger on the controller: serial command and/or parasol action (not a
  physical button). MIDI-driven trigger → backlog.
- Watch: if MIDI arrives over the same serial line, commands must be
  distinguishable from MIDI bytes (controller spec).

## 7. Open decisions (resolve in respective specs)

- MIDI transport: DIN→UART @31250 vs USB-MIDI vs computer-over-serial
  (checking with performer).
- Node addressing / pairing model (unicast to pre-known MAC preferred).
- Voice-stealing policy on polyphony overflow.
- Serial command format + multiplexing with MIDI.

## Backlog

- 1-bit mixing — MVP stretch, drop if it causes ESP-NOW latency problems.
- Mozzi / ESP32Synth for richer synthesis.
- Sustain pedal (CC64) + other CCs.
- MIDI-driven `ENTER_SETTINGS` trigger.
- Solenoid on/off-hold modes (thermal matters).
- acks/retry + dynamic pairing, battery sleep, multi-channel actuators,
  multiple controllers, parasol image upload.
- Switch Arduino → ESP-IDF. Deferred: Arduino is a layer over IDF (raw
  `esp_now_*`/`nvs_*` already callable), so nothing currently forces it.
  Reconsider if parasol requires IDF build-system features (Kconfig/CMake
  components) or if flash/RAM footprint on 12 battery leaves demands it.
  Cost is low and flat while Arduino idioms stay fenced in `src/*_main.cpp`
  and `lib/` stays pure C++.
