# Leaf Firmware Spec

## Purpose

Firmware for the 12 leaf nodes: receive ESP-NOW events (see
`docs/protocol-spec.md`), and drive one actuator — a piezo (plays note
frequencies) or a solenoid (strikes). One codebase, two actuator types,
sharing the receive, config, and mode logic. See `docs/research-notes.md` for
the underlying decisions.

## Architecture

```
leaf firmware
├── ESP-NOW receive (broadcast, channel-first filter)   ← shared
├── heartbeat broadcast (every 10 s)                    ← shared
├── event dispatch → actuator                           ← shared
├── config store (parasol)                              ← shared
├── settings/live mode state machine                    ← shared
├── piezo driver
│   ├── voice table (MAX_VOICES = 8)
│   ├── path A: LEDC (single note + arpeggio)
│   ├── path B: 1-bit mixer (32 kHz timer ISR)
│   └── path M: LEDC monophonic (last-note-wins)
└── solenoid driver (LEDC, fixed 20 kHz)
```

## Voice engine (piezo)

- `voice` = `{ note, velocity, phase, envelope level, envelope stage }`.
- `MAX_VOICES = 8` (compile constant; no runtime setting).
- **Note-on** (`NOTE`, velocity > 0): claim a free voice; if none, steal the
  quietest (then oldest). Set note, velocity, stage = ATTACK.
- **Note-off** (`NOTE`, velocity == 0): find the voice with that note, stage =
  RELEASE. Voice is freed when its envelope reaches 0.
- ADSR stages: ATTACK (level 0 → velocity), DECAY (velocity → sustain),
  SUSTAIN (hold), RELEASE (level → 0). Sustain = percentage of velocity.

## Piezo driver — path A: LEDC (single note + arpeggio)

- One LEDC channel + one timer; frequency = note frequency, duty = amplitude.
- No ISR: a `loop()`-driven control loop runs at ~1 kHz.
  - Every tick: advance each active voice's ADSR; set duty = current voice's
    level (the arpeggiated voice).
  - Every 16.7 ms (60 Hz): advance the arpeggio index, set LEDC frequency =
    current note's frequency (pitch-bend + vibrato applied).
- One active voice = sustained note; several = arpeggiated polyphony.
- Envelope progresses in wall time even while a voice is not the one currently
  sounding (acceptable for the chiptune effect).

## Piezo driver — path B: 1-bit mixer (32 kHz)

- Hardware timer ISR at 32 kHz (~1.1 µs, ~3–4 % CPU for 8 voices).
- Per sample, per active voice:
  - `phase += phaseIncrement` (32-bit).
  - Pulse output high when `phase < (level << 24)` (level is 7-bit, 0–127),
    so duty = level/256.
  - This caps duty at ~50 % at full velocity (square wave = max fundamental;
    level = 0 is off).
  - XOR all active voices' bits, write the result to the actuator GPIO.
- Envelope + vibrato updated at a decimated control rate (~1 kHz) inside the
  ISR.
- `phaseIncrement = freq × 2³² / sampleRate` (64-bit intermediate).

## Piezo driver — path M: monophonic (LEDC, last-note-wins)

- One LEDC channel + timer (same pin as path A). Exactly one note sounds at a
  time: the most recently pressed still-held note.
- A voice is "held" while its stage is ATTACK/DECAY/SUSTAIN; "current" = held
  voice with the highest `born_ms`. Releasing the current note falls back to
  the next most recently pressed held voice (its envelope continues, no attack
  retrigger); releasing the last note lets its release tail ring, then silence.
- Note changes retune the LEDC frequency immediately (~1 ms); continuous pitch
  bend + vibrato retune on the ~60 Hz tick (as path A).
- Selected by `PROGRAM_CHANGE` value 2.

## Expression (piezo)

- **Pitch bend** (14-bit, center 8192): frequency multiplier
  `2^(semitones/12)` over the active voices; range ±2 semitones (configurable).
- **Channel aftertouch**: scales amplitude of all active voices.
- **Poly aftertouch**: scales the amplitude of one note.
- **Vibrato** (`CC1_VIBRATO`): 6 Hz LFO, depth 0–50 cents from CC1 0–127.
  In path A it offsets the retune target; in path B it offsets `phaseIncrement`.
- **Program change**: select render path (0 = LEDC/arpeggio, 1 = 1-bit, 2 = monophonic).

## Note → frequency

- Leaf converts note number to Hz via a 128-entry lookup table (uint16,
  `f = 440 · 2^((n-69)/12)`), 27.5 Hz – 12.5 kHz.
- On the LEDC paths (A/M) the duty resolution is chosen per note (8–14 bits)
  so the full 8 Hz–12.5 kHz table is representable.

## Solenoid driver

- One LEDC channel + timer, fixed ~20 kHz; duty = strike intensity.
- **Note-on**: strike only if `note == my_note` (from parasol config; all
  solenoids share one channel). duty = velocity lookup table; start a ~40 ms
  hold window, then duty = 0.
- **Note-off**: ignored (percussive).
- Retrigger restarts the hold window.
- Hold duration controls ring vs mute (longer = striker pressed against the
  surface = muted) and must exceed the solenoid's pull-in time.
- Velocity→duty lookup table calibrated on hardware (solenoid force is not
  linear in duty).

**Implemented defaults (pending parasol config slice):**
- GPIO 4, LEDC channel 2, timer 1
- ~20 kHz carrier
- `min_duty` / `max_duty` = 40 / 220 (8-bit scale)
- `hold_ms` = 40

## Settings / live mode

- Live = default: ESP-NOW receive + actuator, plus a heartbeat broadcast every
  10 s; radio kept awake (no WiFi stack / web UI).
- Settings = WiFi + parasol web UI, entered briefly after boot or on
  `ENTER_SETTINGS`. Detailed in the config spec.

## Configuration (parasol)

Per-leaf settings: channel, actuator type, GPIO, (solenoid) note, (piezo)
render path + ADSR params + arpeggio rate + pitch-bend range + vibrato depth
range; (solenoid) hold duration + velocity table.

## Defaults (parasol-configurable)

| Setting          | Default                        |
|------------------|--------------------------------|
| Arpeggio rate    | 60 Hz (per-note advance)       |
| Piezo ADSR       | A5 / D100 / S70 % / R100 ms    |
| Pitch-bend range | ±2 semitones                   |
| Solenoid hold duration | 40 ms                     |
| Vibrato          | 6 Hz LFO, 0–50 cents (CC1)     |
| 1-bit sample rate| 32 kHz                         |

## Backlog

- 1-bit mixing — MVP stretch: drop to 16 kHz (or drop the path) if profiling
  shows ESP-NOW interference.
- Voice-stealing refinement (per-voice priority beyond quietest/oldest).
- Per-note vibrato/pitch-bend LFO (currently one LFO per leaf).
- Solenoid power/timing tuning: max power, min push duration, shortest
  noticeable push (calibrate per solenoid).
- Solenoid on/off-hold modes (thermal management).
- Battery sleep / low-power mode in live idle.
  - Idea under consideration: idle-timeout sleep (sleep after N s of
    inactivity, wake on activity) — rejected for the controller because the
    first hit after a pause is exactly the note where latency hurts most in a
    percussion instrument, and a receive-only leaf must wake on packet anyway
    (radio can't fully sleep without jitter on every note). Needs a proper
    wake-on-packet design; configurable duration should be a parasol setting.
- Path B (1-bit 32 kHz mixer) and path M (monophonic) are implemented as of
  the path-B slice; both reuse the voice table + envelope + expression headers
  unchanged. Path B's 32 kHz ISR vs ESP-NOW latency remains a go/no-go that
  must be re-measured on the final hardware.
