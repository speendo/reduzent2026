# Config & Settings/Live Mode Spec

## Purpose

Device configuration via parasol, and the settings/live mode split that keeps
the WiFi stack off during performance. Covers both the controller and the 12
leaves. See `docs/research-notes.md` §6 and the parasol docs.

## Modes

- **Live** (default): ESP-NOW only — no WiFi networking stack, no web UI.
  Low latency and low power.
- **Settings**: WiFi + parasol web UI. The device does not send/receive ESP-NOW
  while being configured.

## Mode state machine

- Boot → Settings for a short window (default 30 s), then → Live.
- Live → Settings on `ENTER_SETTINGS` (leaf) or a serial/parasol action
  (controller).
- Settings → Live on timeout, or when the user saves/exits in parasol.

## WiFi lifecycle

- Settings mode starts WiFi in AP mode (a per-device network, e.g.
  `reduzent-<role>-<id>`) and serves the parasol UI.
- Live mode disables the WiFi stack entirely (ESP-NOW uses the radio without
  the networking stack).
- AP is the MVP default (no shared credentials, configure one device at a
  time); STA mode is backlog.

## Settings (parasol)

### Common (WiFi / ESP-NOW)

- ESP-NOW channel (1–14; must match across the controller and all leaves)
- settings-mode AP SSID + password (per device)

### Leaf

- channel (0–15)
- actuator type (piezo / solenoid)
- GPIO pin
- solenoid: note number, hold duration (ms), velocity min/max power
- piezo: render path (0 = arpeggio, 1 = 1-bit), ADSR (A/D/S/R), arpeggio rate
  (Hz), pitch-bend range (semitones), vibrato depth range (cents)

Hold duration controls ring vs mute (a longer hold presses the striker against
the surface, muting it) and must exceed the solenoid's pull-in time.

### Controller

- settings-mode window duration
- settings-mode trigger (serial / parasol action)

## parasol integration

- Add parasol via `lib_deps` (pinned git tag or release tarball).
- Register settings groups with parasol's C API; provide save callbacks that
  persist to NVS/flash; read values at boot when entering live mode.
- Settings mode = start parasol server; live mode = tear it down.

## Persistence

- Settings persist to NVS, loaded at boot, applied on entry to live mode.

## Backlog

- Compile-time actuator split (separate piezo/solenoid envs) if footprint
  demands.
- STA mode / shared network for configuring many devices at once (needs STA
  SSID + password settings).
- ESP-NOW encryption (PMK/LMK) — only if a shared network needs to be trusted.
- parasol image upload (OTA).
- Solenoid velocity curve as a full editable table (MVP: min/max scalars).
