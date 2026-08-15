# AGENTS.md

## Project

reduzent2026: a central ESP32 controller relays live MIDI over ESP-NOW to
leaf nodes (ESP32-C3) that strike piezo or solenoid actuators. Config via
parasol (settings mode only). See README.md for hardware/wiring details.

## Goals — 5-day build (do only this; rest → backlog)

MVP vertical slice: MIDI in → controller → ESP-NOW → leaf plays.

1. ESP-NOW protocol (compact fixed frame: channel + note + velocity)
2. Leaf firmware: piezo plays note frequency / solenoid strikes its note
3. Controller firmware: MIDI-in → channel/note → node → transmit
4. parasol config (channel→node, note→solenoid, GPIO) in settings mode
5. 12 leaves (6 piezo, 6 solenoid); downsize hardware only if forced.

Backlog: multiple controllers, parasol image upload, acks/retry + dynamic
pairing, battery sleep, multi-channel actuators, solenoid on/off-hold,
switch Arduino → ESP-IDF (only if parasol/footprint forces it).

## Research

Resolved — see `docs/research-notes.md` for decisions and rationale. Key
choices: LEDC PWM output (not mozzi/ESP32Synth); minimal MIDI subset.

## Commands

- Build `pio run` · Upload `pio run -t upload` · Monitor `pio device monitor`
- Clean `pio run -t clean` · Test: native tests for protocol logic (TBD)

## Roles & environment

Board: ESP32-C3-DevKitM-1 (leaf; also the temporary controller this slice)
/ ESP32 classic (final controller, not yet built); Arduino framework.

- leaf (piezo/solenoid, GPIO configurable) · controller
- Separate PlatformIO envs via `src_filter`; shared code in `lib/`.

## Settings / live mode

Devices have two modes. Live = default (no WiFi, low latency). Settings =
parasol web UI, entered briefly after boot or when the controller signals it.

## Protocol & mapping

- ESP-NOW; message carries channel + note + velocity.
- Piezo: channel → node, note → frequency, velocity → amplitude.
- Solenoid: one shared channel, note selects which solenoid, velocity → intensity.

## Conventions

- Small footprint (battery-powered).
- Write comments that aid readability.
- Verify before finishing: `pio run` compiles, logic tested natively, and
  check for redundant / low-quality / inefficient code.

## Git

- The user pushes to GitHub themselves; agents only commit but never push.
- Branch per feature or component (e.g. a firmware module), not per document.
  Small docs/fixes may go straight to `main`.

## Workflow

- Use superpowers skills: brainstorm → plan → TDD → verify.
- Every brainstorm ends by splitting the idea into now vs. backlog.
- Specs: one file per topic, with a `## Backlog` section for deferred items.
