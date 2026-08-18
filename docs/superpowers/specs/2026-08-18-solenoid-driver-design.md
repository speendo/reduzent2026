# Solenoid Driver Design

Date: 2026-08-18
Status: draft for review

## Purpose

Give the leaf firmware a solenoid strike driver: receive ESP-NOW `EVENT_NOTE`
on the leaf's shared channel, and when the note matches the solenoid's assigned
note, strike the actuator (LEDC PWM at ~20 kHz, duty from velocity, for a fixed
hold window). Percussive: note-off is ignored. This completes MVP goal 2's
solenoid half (piezo is already implemented as paths A/B/M).

## Goals / non-goals

Goals:

- A pure-logic, natively testable solenoid state machine in `lib/reduzent/`
  (note-match, strike, retrigger, hold-window timing, note-off ignored).
- Velocity→duty scaling implemented with configurable variables (not a
  hardcoded table), leaving a clear seam where a calibrated, parasol-editable
  table slots in later.
- Solenoid wiring in `src/leaf_main.cpp` on a hardcoded GPIO (pin 4) mirroring
  the piezo's `#define` pattern, on its own LEDC channel + timer.
- Strike force / hold-duration quality verified manually on hardware later.

Non-goals (backlog):

- parasol / NVS configuration of solenoid settings (pin, note, hold duration,
  velocity curve) — a separate config/settings slice.
- Velocity→duty lookup-table calibration on hardware.
- Solenoid on/off-hold modes (thermal management).
- Battery sleep / low-power idle.

## Overview

One shared MIDI channel carries all solenoid leaves (per project protocol:
"solenoid: one shared channel, note selects which solenoid"). Each solenoid
leaf is configured with `my_note`; it strikes only on a note-on whose note
matches, energizing the coil at a velocity-derived duty for `hold_ms`, then off.

State machine (pure logic, header-only like the rest of `lib/reduzent/`):

- **Note-on** (`EVENT_NOTE`, velocity > 0) where `note == my_note`: set
  `active_until = now + hold_ms`, remember the strike duty. A retrigger (second
  matching note-on while active) restarts the window.
- **Note-off** (`EVENT_NOTE`, velocity == 0): ignored. Percussive.
- **Hold expiry**: when `now >= active_until`, the actuator returns to duty 0.
  Checked once per `loop()` tick (like the piezo watchdog).

## Velocity → duty

- Linear scale between two configurable endpoints: `min_duty` (velocity 1) and
  `max_duty` (velocity 127). Velocity 0 never reaches the striker (it is a
  note-off). Clamped to the LEDC resolution's valid range.
- Implemented as variables (defaults `min_duty`, `max_duty`) so later parasol
  settings can write them; a comment marks where a calibrated lookup table
  (parasol) would replace the linear formula.
- **Suggested defaults for testing:** `min_duty = 40`, `max_duty = 220` on the
  8-bit scale (0–255), i.e. `duty(vel) = 40 + 180 * (vel − 1) / 126`, clamped.
  Rationale: `max_duty = 220` leaves ~14 % headroom below full duty to avoid
  battery/step-up sag and coil heating on repeated hits; `min_duty = 40` is a
  soft tap that is plausibly above the plunger's pull-in threshold. Both are
  placeholders to be calibrated on hardware.
- Strike envelope: energize at the computed duty for the full hold window, then
  off — no fade (a striker needs force, not envelope shaping).

## Hardware / wiring

- GPIO 4 — a plain GPIO on the ESP32-C3 (not a strapping pin; the piezo already
  uses GPIO 3).
- LEDC: one channel + one timer separate from the piezo's (channel 2, timer 1 —
  the Arduino core maps `timer = (chan/2) % 4`, so channel 2 is timer 1).
  Rationale: LEDC frequency is a per-timer property; the piezo retunes its timer
  on every note and must not disturb the solenoid's fixed ~20 kHz. A leaf hosts
  exactly one actuator today, so they never run concurrently, but the
  separation is free (C3 has 6 channels / 4 timers) and future-proofs a
  dual-actuator leaf.
- ~20 kHz carrier; duty resolution 8-bit (matches `PWM_RES`, plenty for 7-bit
  velocity).
- Drive through a MOSFET + flyback diode across the coil (board-level; out of
  firmware scope).

## Files

- Create `lib/reduzent/solenoid.h` — the pure state machine (TDD, native tests).
- Modify `src/leaf_main.cpp` — `#define`s (pin 4, channel 2, timer 1, note, hold
  duration), the `EVENT_NOTE` handler to consult the solenoid for matching
  notes, and a hold-expiry check in `loop()`.
- Create `test/test_solenoid/test_solenoid.cpp` — Unity tests for the pure
  logic.

## Testing

Native (PlatformIO Unity), run with `pio test -e native`:

- Note-on matching `my_note` starts a strike (duty set, window armed).
- Non-matching note is a no-op.
- Note-off (velocity 0) is ignored.
- Retrigger restarts the hold window (extended `active_until`).
- Hold expiry returns duty to 0 after `hold_ms`.
- Velocity→duty: clamps at low/high velocities; monotonic between endpoints;
  velocity 0 produces no strike.
- Firmware still builds: `pio run -e leaf`, `pio run -e controller`.

Manual (hardware, later): strike force vs. velocity, hold-duration ring/mute
trade-off — calibrate on the real actuator.

## Backlog

- parasol config: solenoid pin, note, hold duration, velocity curve.
- Calibrated velocity→duty lookup table.
- Solenoid on/off-hold modes (thermal management).
- Battery sleep in live idle.
