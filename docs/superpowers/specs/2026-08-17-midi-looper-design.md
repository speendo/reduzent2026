# MIDI Looper Design

Date: 2026-08-17
Status: draft for review

## Purpose

A live looper for the reduzent controller, implemented as a new standalone
script `tools/looper.py` that records a multitrack loop from live MIDI and
plays it back to the controller over serial. It is additive to the existing
`tools/midi_bridge.py`: live MIDI always passes straight through to the
controller, and the looper records a copy and re-emits it on a schedule.

## Goals / non-goals

Goals:

- Record a loop channel-by-channel: the first recording defines the loop
  length; later recordings on other channels are overdubs aligned to the loop's
  phase (the "seam catch").
- Re-recording a channel replaces its track; a hotkey deletes a track; a hotkey
  mutes/unmutes a track.
- Global tempo-only playback rate (0.25–4.0×), pitch unchanged.
- Save/load a loop to/from a human-readable file; load replaces the current loop.
- Remain a separate script that imports `midi_bridge`'s pure helpers; a minimal,
  behavior-preserving refactor of `midi_bridge` to expose one shared helper.

Non-goals (backlog):

- Additive overdub (merging a new take onto an existing track) — recording a
  channel *replaces* its track.
- MIDI-clock sync, BPM-quantized recording, beat-grid snapping.
- Tape-style speed (pitch follows rate); pitch-bend/aftertouch re-encoding.
- Global mute / kill-switch; persisting the rate or mute state with the loop.

## Architecture

```
tools/looper.py (new)
├── imports from midi_bridge: midi_to_command, load_settings, save_settings,
│   resolve_settings, menu_choice, select_ports, open_connections,
│   DEFAULT_CONFIG, setup_scroll_region, reset_scroll_region, raw_terminal
├── model: Loop { length, tracks: {channel → Track}, anchor }
│   Track { events (phase-sorted), muted }
│   Event { phase, seq, cmd }      # cmd = reduzent text command, channel embedded
├── record: stamps incoming MIDI (post-override) into the selected track
├── playback: scheduler thread emitting due events through the shared serial path
└── save/load: flat text log ↔ model
```

The data model is normalized to **master seconds at 1.0×**. `length` is the
first recording's wallclock duration. Each event's `phase` is a position in
`[0, length)`. `anchor` is a monotonic reference time set when the first
recording starts (so phase 0 = that moment); playback and later overdubs
derive their phase from it.

## Reuse & refactor of midi_bridge.py

- `midi_to_command()` and the settings/port helpers are already module-level and
  importable; `main()` is already `__name__`-guarded.
- Minimal refactor: extract the inline `termios`/`tty` raw-mode setup/teardown
  into a `raw_terminal(fd)` context manager (yields the previous termios attrs)
  so both scripts share it. `midi_bridge.main()` uses it for its top-level
  raw-mode block; its inner `input()`-prompt pattern keeps working via the
  yielded `old` attrs.
- Behavior of `midi_bridge.py` is unchanged; `tools/test_midi_bridge.py` must
  still pass. The looper owns its own runtime (raw-key loop, connection
  management, scheduler, status bar) — the raw-terminal/reconnect skeleton is
  intentionally not abstracted further, to avoid touching feature-complete code.

## Captured commands

A loop captures `n x p a pa v` (note on/off, pitch bend, channel/poly
aftertouch, CC1 vibrato). `g` (program change) and `panic` are *not* recorded —
they are mode/control signals, not musical content. Events are stored with the
reduzent text command exactly as produced by `midi_to_command`, so the channel
is embedded in the command and no separate channel field is needed.

## Recording (space toggles)

- **No loop yet:** first press starts a fresh loop; `anchor` is set and events
  are stamped `phase = now − start`. Second press stops and sets `length`.
- **Loop exists:** recording on the selected channel stamps
  `phase = ((now − anchor) × rate) % length`. Because every event is stamped
  against the *audible* phase, overdubs align with the current playback rate;
  the seam catch is automatic. A note crossing the seam stores `on` at a late
  phase and `off` at an early phase of the next cycle and plays back correctly.
- **Stop:** synthesize a note-off for any note still held at stop time, then
  **replace** the target track. While re-recording a channel, its existing track
  is muted until the new take commits.
- The recorded channel is the post-`c`-override channel (so `c` doubles as the
  record target). Live MIDI always passes through unchanged, during and outside
  recording.

## Playback scheduler

- A dedicated thread computes `phase = ((now − anchor) × rate) % length` and
  emits every event whose phase has come due. It sleeps only when no loop
  exists, so the bridge's event-driven idle behavior is preserved in looper-less
  sessions.
- Emission uses the same serial-write path as `midi_bridge`: a shared lock over
  the serial handle, with the same reconnect-on-failure logic.
- Per-track mute suppresses a channel's events; the global rate scales all
  channels together (a per-channel rate would desync the shared timeline).

## Rate scaling & representation

Tempo-only scaling re-emits each command with its value **unchanged**; only the
wallclock timing scales. No command value ever needs re-encoding (this is why
tempo-only was chosen over tape-style, which would force re-encoding
pitch-bend/aftertouch/vibrato values). Storage is always normalized at 1.0×,
and rate is applied only at playback, so the file format is rate-independent
and lossless. The remaining temporal edges are accounted for explicitly:

- **Ordering/collision:** each event carries a monotonic `seq` (file line
  order). Playback emits all due events in `(phase, seq)` order within a tick,
  so a note-on always precedes its note-off even when a fast rate compresses
  them into the same tick. The scheduler emits bursts (all due events per wake),
  never one-sleep-per-event, so dense sections at 4× do not drift.
- **Duration ambiguity at the seam:** a circular loop cannot distinguish a note
  held `0` from one held exactly `k × length`. A note whose `off` phase wraps to
  equal its `on` phase is therefore clamped to a **full-length note**
  (`duration = length`). A normal seam-crossing note (`off < on`) is
  `(off − on) mod length`.
- **Precision:** phases are stored losslessly (floats serialized to microsecond
  precision), independent of rate; the minimum representable gap is set by the
  file format, not by the playback rate.

The practical ceiling at high rates is the serial link and leaf rendering
(minimum strike/tone duration), not the representation — documented as a
limitation (see backlog).

## Hotkeys

- `space` record/stop · `d` delete selected channel's track · `x` mute/unmute
  selected channel · `w` save (prompt name) · `r` load (numbered list) ·
  `+`/`=` rate up · `-` rate down · `0` reset rate to 1.0×.
- Inherited for parity: `c` channel (record target), `i` instrument,
  `m` port menu, `s` settings, `q` quit.
- Rate is **live-only**: 0.25–4.0×, step 0.05, not saved (files always store
  1.0× events).

## Save format

Files live in `~/.config/reduzent/loops/<name>.loop`; `w` prompts for a name,
`r` lists existing files for selection. Loading **replaces** the current loop.
Deleting the last track resets the loop (the next record defines a fresh
length).

```
reduzent-loop v1
length 4.0
0.000000 n 0 60 100
0.000000 v 0 64
0.500000 x 0 60
1.250000 n 3 67 90
```

Each line is `<phase> <command>`, reusing the exact reduzent text vocabulary.
Line order is the event `seq` and is preserved on load, so ordering survives a
round-trip. Unknown/legacy header lines are ignored gracefully on load.

## Error handling / edge cases

- Recording with no channel override records events under their own MIDI
  channel (the post-override channel is the MIDI channel when `c` is unset).
- Save/load I/O errors print a message and leave the loop untouched.
- Serial write failure during playback uses the same retry/reconnect path as
  live forwarding.
- Live MIDI and loop playback both drive the leaf's expression state (pitch
  bend/aftertouch/vibrato); a live bend can interact with a loop's bend. This is
  inherent to "live always passes through" and is accepted, not papered over.

## Testing

Native unit tests in `tools/test_looper.py`, with a fake clock (no real sleeps),
covering the pure logic:

- Phase stamping: fresh-loop recording; overdub `((now − anchor) × rate) % length`;
  seam-wrap (`off < on`).
- Dangling-note close on stop; replace/delete/mute state transitions.
- Note-duration clamping at the seam (full-length when `off == on`).
- Serialize/parse round-trip preserves `seq` order and phases.
- Scheduler: "events due at phase `p`" returns the correct (phase, seq)-ordered
  set, including burst/collision cases.
- `midi_bridge` regression: `tools/test_midi_bridge.py` still passes after the
  `raw_terminal` refactor.

Real-time scheduling precision and serial/MIDI I/O are exercised manually (as
with `midi_bridge` today).

## Backlog / out of scope

- Additive overdub (merge onto an existing track).
- Persist rate/mute with the loop; global mute/kill-switch.
- MIDI-clock sync; BPM-quantized recording (pulls the controller backlog
  forward).
- Minimum-note-duration floor enforcement at high rates (leaf render limit).
- Undo/redo, track solo, per-track loop-length (poly-meter).
