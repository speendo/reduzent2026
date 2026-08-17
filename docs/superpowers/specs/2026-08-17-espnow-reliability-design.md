# ESP-NOW Reliability Design

Date: 2026-08-17
Status: approved for implementation

## Purpose

ESP-NOW is fire-and-forget broadcast, so frames are occasionally dropped. A
dropped note-on is a missed note (acceptable), but a dropped note-off leaves a
voice stuck in `ENV_STAGE_SUSTAIN` forever — a note that rings indefinitely.
This design makes the link self-healing so no single dropped frame can strand a
note, and adds explicit "silence" controls (global + per-channel) that survive
the same unreliable link.

## Goals / non-goals

Goals:

- Bound the duration of a stuck note after a dropped note-off.
- Self-heal dropped note-ons within one keepalive interval.
- Global panic (hard stop) and per-channel silence (release), both robust to
  being dropped themselves.
- MIDI-correct CC120/121/123 handling (distinct hard stop vs. release vs.
  controller reset).

Non-goals (backlog):

- Acks/retry, unicast MAC table, per-frame sequence counters.
- Redundant transmission of ordinary note-on/note-off (drops are "acceptable"
  for note-on; the watchdog covers the note-off case).
- Multi-channel actuators (a leaf on several channels).

## Overview: three mechanisms

1. **Hold keepalive + watchdog** (the core). The controller periodically
   re-affirms every held note via a new `NOTE_HOLD` event; the leaf auto-releases
   any `SUSTAIN` voice whose last affirmation is older than `X` ms. A dropped
   note-off is therefore released within ~`X` ms; a real long hold is
   continuously re-affirmed and never cut.
2. **Hard stop (panic)** — the existing `EVENT_PANIC`, extended to a per-channel
   scope and sent redundantly so a "silence now" button cannot itself be lost.
3. **Soft stop (notes off)** — a new `EVENT_NOTES_OFF` that releases all notes
   on a channel with their release tails (CC123 "All Notes Off" semantics).

## Protocol changes

The fixed 5-byte frame is unchanged. Add three event types and extend one:

- `EVENT_NOTE_HOLD = 9` — `channel` + `note` + `value` (velocity); `value_hi`
  unused. Keepalive refresh.
- `EVENT_NOTES_OFF = 10` — `channel` (0–15, or `0xFF` = all). Release all active
  notes with tails.
- `EVENT_RESET_CONTROLLERS = 11` — `channel` (0–15, or `0xFF` = all). Reset
  expression state to neutral.
- `EVENT_PANIC` (existing, 6) — `channel` is now `0xFF` = all leaves, or `0–15`
  = one channel's leaf. Hard stop (unchanged behavior).

## Controller

- Held-note table `held[16][128]` of `uint8_t`, storing velocity (0 = not held).
- `n`/`x` maintain the table and transmit the NOTE frame exactly as today.
- Keepalive: every `R = X/Y` ms, walk the held table and send one `NOTE_HOLD`
  per held note (carrying its velocity). Each held note is therefore re-affirmed
  once per `R`.
- `panic [<ch>]` and `noff [<ch>]`: clear the held table for the scope (all or
  one channel), then transmit the event **three times** (a dropped panic/noff
  must not silently fail).
- `resetcc [<ch>]`: transmit once (non-destructive; a drop merely leaves a bend
  in place until the next real message).
- Clearing the held table is mandatory: without it the next keepalive tick
  re-sends `NOTE_HOLD`, and the leaf's "else note-on" resurrects the silenced
  notes.

## Leaf (piezo)

- `voice_t` gains `hold_refresh_ms`, set on note-on and on each `NOTE_HOLD`.
  (A separate field from `born_ms`, which must keep meaning "most recently
  pressed" for the monophonic path.)
- `NOTE_HOLD`: if a voice with that note is active, refresh its
  `hold_refresh_ms`; otherwise `voice_note_on` (self-heals a dropped note-on).
  Piezo only — solenoid leaves ignore this event.
- Watchdog, run each control tick: any voice in `SUSTAIN` with
  `now - hold_refresh_ms > X` is forced into `RELEASE`.
- `NOTES_OFF`: release all active voices (tails ring).
- `RESET_CONTROLLERS`: pitch bend → center, vibrato → 0, aftertouch → 127 (the
  neutral value of our amplitude encoding — see "MIDI mapping").
- `PANIC`: unchanged hard stop (`voice_table_init` + silence).

## MIDI bridge (tools/midi_bridge.py)

- Hotkeys: `p` → global panic (`panic`); `o` → channel silence (`noff <ch>`).
- Active channel = the `c`-key override if set, else the most recent forwarded
  note's channel; if neither, print a hint and send nothing.
- CC mapping (per-channel, per MIDI semantics):
  - CC120 "All Sound Off" → `panic <ch>` (hard stop)
  - CC121 "Reset All Controllers" → `resetcc <ch>`
  - CC123 "All Notes Off" → `noff <ch>` (release)

## MIDI mapping nuance

MIDI's default for aftertouch is 0 (no pressure), but this leaf encodes
aftertouch as a straight amplitude scale where `127 = full, 0 = mute`
(`scale_level`, expression.h). So "reset aftertouch to neutral" means 127 in our
encoding, not MIDI's literal 0. `EVENT_RESET_CONTROLLERS` therefore restores
neutral (`127`), which is behaviorally correct; the inversion is a pre-existing
encoding quirk, recorded in the backlog rather than changed here.

## Ordering assumption

`NOTE_HOLD`'s "else note-on" relies on ESP-NOW delivering a single controller's
frames in FIFO order, so a stale refresh always precedes a later note-off/panic
and never resurrects a note after it was silenced. This holds for broadcast from
one sender; note it if a second controller is ever added (backlog).

## Parameters

- `X = 3000 ms` (worst-case stuck-note duration after a dropped note-off).
- `Y = 4` (keepalive redundancy factor).
- Keepalive interval `R = X / Y = 750 ms`.
- Relationship: `X = Y * R` gives tolerance for ~`Y-1` consecutive dropped
  refreshes before a held note is (incorrectly) released.
- Compile constants for now; parasol-configurable later.

## Error handling / edge cases

- Solenoid leaves: `NOTE_HOLD`, `NOTES_OFF`, `RESET_CONTROLLERS` are no-ops
  (percussive; no sustain, no expression).
- Dropped panic/noff: three redundant copies; residual risk is the leaf watchdog
  releasing within `X`.
- Re-striking the same note inside a keepalive window is safe: `NOTE_HOLD`
  refreshes an active voice and never re-attacks it.
- The held table only ever grows with held notes and is cleared by panic/noff,
  so it cannot leak unbounded.

## Testing

Native (Unity) tests in `test/`:

- Held-note table: set/clear/iterate/scope-clear.
- Text parser: `panic`, `panic <ch>`, `noff`, `noff <ch>`, `resetcc`,
  `resetcc <ch>`, and that `noff` is not misparsed as note-on.
- `NOTE_HOLD` logic: refreshes an active voice; starts a missing note.
- Watchdog: a `SUSTAIN` voice past `X` is released; a refreshed voice is not.
- Bulk notes-off releases all active voices.
- Frame pack/unpack extended for the new event types.

## Backlog / out of scope

- Redundant ordinary note-on/note-off.
- Acks/retry; unicast MAC table; sequence counters for out-of-order tolerance.
- Parasol-configurable `X`/`R`.
- Clean up the inverted aftertouch encoding (127 = full).
- Multi-controller support (relaxes the single-sender FIFO assumption).
