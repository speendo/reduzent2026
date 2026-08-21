# MIDI Looper Design

Date: 2026-08-17
Status: implemented
Note: the Hotkeys and Status bar sections are superseded by
`2026-08-21-looper-nav-design.md` (channel selection, navigation, channel
column, MIDI hotkeys).

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
- Version the loop's genesis in git (one repo per loop): once the loop is first
  named (`w` save), every state change — take commit, delete, mute/unmute —
  auto-writes `loop.loop` and commits; before the first save the loop is
  in-memory only (no file, no history). Mute state is part of the saved file.
- Remain a separate script that imports from a shared helpers module (never
  from `midi_bridge` directly); a behavior-preserving extraction of the shared
  functions into that module.

Non-goals (backlog):

- Additive overdub (merging a new take onto an existing track) — recording a
  channel *replaces* its track.
- MIDI-clock sync, BPM-quantized recording, beat-grid snapping.
- Tape-style speed (pitch follows rate); pitch-bend/aftertouch re-encoding.
- Global mute / kill-switch; persisting the playback rate with the loop.

## Architecture

```
tools/looper.py (new)
├── imports from reduzent_shared (never from midi_bridge):
│   midi_to_command, load_settings, save_settings, resolve_settings,
│   menu_choice, select_ports, open_connections, DEFAULT_CONFIG,
│   setup_scroll_region, reset_scroll_region, raw_terminal
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
derive their phase from it. Loading a loop sets `anchor` to the load moment, so
a loaded loop starts playback at phase 0 regardless of how or where it was
saved.

## Reuse & refactor of midi_bridge.py

- The shared surface moves to a new module `tools/reduzent_shared.py`:
  `midi_to_command`, `load_settings`, `save_settings`, `resolve_settings`,
  `menu_choice`, `select_ports`, `open_connections`, `DEFAULT_CONFIG`,
  `DEFAULT_BAUD`, `setup_scroll_region`, `reset_scroll_region`, and a new
  `raw_terminal(fd)`
  context manager (extracted from `midi_bridge`'s inline `termios`/`tty`
  raw-mode setup/teardown; it yields the previous termios attrs so the
  `input()`-prompt pattern keeps working).
- `midi_bridge.py` imports those names back from `reduzent_shared` (they remain
  module attributes, so `tools/test_midi_bridge.py`'s `from midi_bridge import
  ...` keeps working) and keeps its own runtime: override handling, reconnect,
  status bar, main loop. Its behavior is unchanged.
- `looper.py` imports from `reduzent_shared` only — never from `midi_bridge` —
  so later changes to `midi_bridge.py` cannot break the looper. The shared
  module is the single stable seam between the two scripts.
- The looper owns its own runtime (raw-key loop, connection management,
  scheduler, status bar) — the raw-terminal/reconnect skeleton is intentionally
  not abstracted further, to avoid pulling feature-complete code into the shared
  module.

## Captured commands

A loop captures `n x p a pa v` (note on/off, pitch bend, channel/poly
aftertouch, CC1 vibrato). `g` (program change) and `panic` are *not* recorded —
they are mode/control signals, not musical content. A take may additionally end
with auto-generated `x <ch> <note>` note-offs (the seam-closing close, see
Recording); they are synthesized at stop, never captured from live MIDI. Events
are stored with the reduzent text command exactly as produced by
`midi_to_command`, so the channel is embedded in the command and no separate
channel field is needed.

## Recording (space toggles)

- **Control:** `space` is the first-class control for both starting and
  stopping a take — one key, no separate arm mode. There is no arming step:
  pressing `space` either starts a take (if none is in progress) or stops it
  (if one is). While recording, playback of the existing loop continues and
  live MIDI passes through as usual; `space` alone stops the take. The
  start/stop behavior below is identical whether a loop exists or not.
- **No loop yet:** first press starts a fresh loop; `anchor` is set and events
  are stamped `phase = now − start`. Second press stops and sets `length`.
- **Loop exists:** recording on the selected channel stamps
  `phase = ((now − anchor) × rate) % length`. Because every event is stamped
  against the *audible* phase, overdubs align with the current playback rate;
  the seam catch is automatic. A note crossing the seam stores `on` at a late
  phase and `off` at an early phase of the next cycle and plays back correctly.
- **Over-record (recording past one loop):** because a take replaces the whole
  channel track (no additive layering), the wrap is destructive — keep a take
  to one loop. Events stamped via `% length` land on the same phases every
  cycle, so if the take runs past one loop, the later cycle's events **overwrite**
  the earlier cycle's at the same phases: a note replayed in a later cycle
  replaces the earlier occurrence, and a note played only in the first cycle is
  dropped. The committed track is what you played on the *final* pass through
  the timeline. A seam-crossing note held across the wrap is the intended
  exception — its `off` lands at the early phase of the next cycle and closes it.
  At fast rates (2×/4×) this is the norm, not the exception: one audible loop is
  only `length / rate` wallclock seconds, so a take that runs even slightly long
  wraps, and the final-pass-wins rule keeps fast overdubs clean instead of
  layering duplicated notes every cycle.
- **Fresh-length rule:** a recording defines a fresh length when the loop
  starts with zero tracks **or exactly one track (which this take replaces)**;
  the "loop exists" branch above applies only when ≥2 tracks remain. So a first
  recording, a full wipe (all tracks deleted), and a lone-track overwrite (all
  but one deleted, the survivor re-recorded) are handled identically.
- **Re-recording an existing channel:** the channel's current track is muted
  for the whole take (its playback is silenced, and a `noff <ch>` releases its
  sustaining notes) while live keys still pass through to the leaves as usual.
  `space` again **commits** the take: the old track on that channel is deleted
  and replaced by the new one. Cancelling the take (see below) discards it and
  restores the old track's prior mute state, leaving the loop unchanged.
- **Stop:** two effects, using different commands:
  - *Live:* send `noff <ch>` (channel-scoped notes-off) to the controller to
    release the notes still held at the stop moment — one channel-wide command,
    no held-note bookkeeping.
  - *Recorded:* stamp one `x <ch> <note>` per note still held at stop, at the
    stop phase, as the take's final events. This makes the take self-closing on
    playback — a dangling note-on would otherwise re-attack every cycle and ring
    forever (the controller's keepalive keeps it alive). Per-note offs never cut
    a seam-crossing sustain on a different note; on solenoid leaves an off is a
    harmless no-op (percussive, no sustain).
  Then commit (replace) the target track as described above.
- **Cancel (`d`):** while a take is in progress, `d` cancels it — the same
  hotkey that deletes a track when not recording. `d` is therefore
  context-sensitive: not recording → deletes the selected channel's track;
  recording → aborts the take. A cancelled take is thrown away and never
  commits; it has zero effect on the loop:
  - *First take ever (no loop yet):* the take is discarded and the looper
    reverts to "no loop" — no length is set, and the next `space` starts a
    completely fresh recording.
  - *Re-recording over an existing channel:* the new take is discarded and the
    old track is restored with its prior mute state — playing exactly as before,
    as if the re-record never happened.
- **Single-channel takes:** a take records onto exactly one channel — the `c`
  override if set, otherwise the channel of the first note recorded in the take
  (locked for that take). Notes arriving on other channels during the take pass
  through live but are not recorded. `c` therefore doubles as the record target.
  Live MIDI always passes through unchanged, during and outside recording.

## Playback scheduler

- A dedicated thread computes `phase = ((now − anchor) × rate) % length` and
  emits every event whose phase has come due. It sleeps only when no loop
  exists, so the bridge's event-driven idle behavior is preserved in looper-less
  sessions.
- Emission uses the same serial-write path as `midi_bridge`: a shared lock over
  the serial handle, with the same reconnect-on-failure logic.
- **Concurrency:** that shared lock also guards the `Loop` model. The scheduler
  thread snapshots the due events under the lock before emitting them, so
  recording (main thread) and playback never observe a half-mutated track.
- Per-track mute suppresses a channel's events; the global rate scales all
  channels together (a per-channel rate would desync the shared timeline).
- **Release on mute/delete:** muting, deleting, or re-recording a channel also
  sends `noff <ch>` so notes sustaining from that track — which would otherwise
  ring forever (no note-off ever comes; keepalive holds them) — are released.
  `noff` releases every note on the channel, including a live note held at that
  instant; the collateral is accepted, since these actions are deliberate
  channel silences.

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

- `space` record/stop · `d` delete selected channel's track (or cancel a take
  in progress) · `x` mute/unmute selected channel · `p` panic + halt ·
  `o` channel silence · `w` save (prompt name) · `r` load (numbered list) ·
  `+`/`=` rate up · `-` rate down · `0` reset rate to 1.0×.
- Inherited for parity: `c` channel (record target), `i` instrument,
  `m` port menu, `s` settings, `q` quit.
- **Channel silence (`o`):** sends `noff <ch>` for the active channel (the `c`
  override if set, else the most recent note's channel) as a one-shot release —
  no state change, the track keeps playing. Parity with `midi_bridge`.
- **Selected channel:** `d` (delete) and `x` (mute) act on the *selected
  channel*, which is the active channel — the `c` override if set, else the
  channel of the most recent note — exactly as in `midi_bridge`. With no
  override and no note seen yet, `d`/`x` are no-ops.
- **Panic + halt (`p`):** sends `panic` (global hard stop — all leaves
  silenced, held table cleared, sent 3×) and, when a loop exists and no take is
  in progress, **halts playback**: the scheduler pauses at its current phase and
  emits nothing. `p` again resumes from the same phase (tape-pause — the anchor
  is shifted so the phase continues, independent of rate). While halted, `space`
  is inert (resume with `p` first); editing (delete/mute/save/load/rate) still
  works. During a take, `p` only sends the live panic and the take keeps
  recording (use `d` to cancel). With no loop, `p` just silences live MIDI.
- Rate is **live-only**: 0.25–4.0×, step 0.05, not saved (files always store
  1.0× events).

## Status bar

The looper redraws `midi_bridge`'s two-line status bar, extended with loop
state. Line 1: port/baud, loop name (or "no loop"), length, track count, and
rate. Line 2: current channel — `c` override (tagged `(override)`) else most
recent note's channel (`(MIDI)`) — and instrument (`i` override else last
program), plus the looper hotkey help line.

## Save format

Loops live as per-loop git repos: `~/.config/reduzent/loops/<name>/` holds
`loop.loop` (the save file) and `.git` (its history), so one repo = one loop.
`w` prompts for a name (sanitized to a safe directory name; empty input
cancels) and overwrites silently if it already exists; `r` lists existing loops
for selection. Loading **replaces** the current loop. Deleting tracks down to
zero — or to one, whose next take replaces it — resets the loop; the next record
defines a fresh length (see the fresh-length rule under Recording). Mute state
is part of the file: a `mute <ch>` header line per muted track, restored on
load.

```
reduzent-loop v1
length 4.0
mute 3
0.000000 n 0 60 100
0.000000 v 0 64
0.500000 x 0 60
1.250000 n 3 67 90
```

Each line is `<phase> <command>`, reusing the exact reduzent text vocabulary
(`mute <ch>` is a header line, not an event). Line order is the event `seq`
and is preserved on load, so ordering survives a round-trip. Unknown/legacy
header lines are ignored gracefully on load.

An empty loop ("no loop") is stored as `length 0.0` with no event lines.
Deleting all tracks auto-writes and commits that empty state, so a reset is a
versioned genesis step like every other; loading an empty file restores the
"no loop" state, and the next record applies the fresh-length rule.

## Loop genesis (git)

Each named loop's repo records its own history. The first `w` (named save)
creates the repo and commits the current state as the genesis step. From then
on, every state change — a take being committed, a track deleted, a track
muted/unmuted — auto-writes `loop.loop` and commits (`git add` + `git commit`),
so every take and edit is a versioned step: the loop's evolution is traceable
and any earlier state can be inspected or reverted. Before the first save, the
loop is in-memory only: no file, no repo, no history (nothing to lose on quit).

- Auto-write is internal bookkeeping: it never prompts and is separate from the
  named `w` save; both write the same format (including mute state).
- A commit is skipped when the state equals the last commit (no-op guard).
- Deleting all tracks commits the empty state (`length 0.0`, see Save format),
  so a full reset is a versioned step too; the repo keeps the loop's whole
  history, including resets.
- Graceful degradation: if `git` is unavailable or a repo is broken, warn once
  and continue without versioning.
- Loading a loop switches the working repo; the replaced in-memory state is
  already committed (once named), so nothing is lost.

## Error handling / edge cases

- Recording with no channel override locks the take to the first note's MIDI
  channel; subsequent notes on other channels are live-passed but not recorded
  (single-channel take; multi-channel takes are backlog).
- Save/load I/O errors print a message and leave the loop untouched.
- Serial write failure during playback uses the same retry/reconnect path as
  live forwarding.
- Live MIDI and loop playback both drive the leaf's expression state (pitch
  bend/aftertouch/vibrato); a live bend can interact with a loop's bend. This is
  inherent to "live always passes through" and is accepted, not papered over.
- A take closed while notes were held replays `x <ch> <note>` offs at its stop
  phase each cycle; a live note on the same channel/note at that phase is also
  released. Same accepted live-vs-loop interaction as above.
- A note already held when a take starts is not recorded (its note-on predates
  the take); the take captures only notes played during it. Accepted.
- `w`/`r`/`q` are ignored while a take is in progress (finish or cancel it with
  `space`/`d` first).

## Testing

Native unit tests in `tools/test_looper.py`, with a fake clock (no real sleeps),
covering the pure logic:

- Phase stamping: fresh-loop recording; overdub `((now − anchor) × rate) % length`;
  seam-wrap (`off < on`).
- Dangling-note close on stop: emits `noff <ch>` live and records one
  `x <ch> <note>` per held note at the stop phase; a take with nothing held
  records no closing events. Replace/delete/mute state transitions.
- Release on mute/delete/re-record: each emits `noff <ch>` for the affected
  channel; cancel of a re-record restores the track's prior mute state.
- Panic/halt: `p` sends `panic` and freezes the phase; resume continues from
  the same phase (anchor shift).
- Note-duration clamping at the seam (full-length when `off == on`).
- Serialize/parse round-trip preserves `seq` order, phases, and the `mute`
  header, and round-trips the empty state (`length 0.0`, no events).
- Genesis commit decision: a commit is made only when the state differs from the
  last commit (no-op skip); git I/O itself is exercised manually.
- Scheduler: "events due at phase `p`" returns the correct (phase, seq)-ordered
  set, including burst/collision cases.
- `midi_bridge` regression: `tools/test_midi_bridge.py` still passes after the
  extraction of `reduzent_shared` (including the new `raw_terminal`).

Real-time scheduling precision and serial/MIDI I/O are exercised manually (as
with `midi_bridge` today).

## Backlog / out of scope

- Additive overdub (merge onto an existing track).
- Multi-channel takes (record notes across several channels in one take).
- Persist the playback rate with the loop; global mute/kill-switch.
- MIDI-clock sync; BPM-quantized recording (pulls the controller backlog
  forward).
- Minimum-note-duration floor enforcement at high rates (leaf render limit).
- Undo/redo, track solo, per-track loop-length (poly-meter).
- **Genesis playback sequencing (open question):** how to track how many times
  the current state should repeat in playback — sequencing historical states
  (state A × k loops, state B × m loops, …) and keeping that repeat-count with
  the state.

## Implementation slices

Five sequential slices, each ending in an independently testable deliverable.
Each slice gets its own plan under `docs/superpowers/plans/`. The interface
contract below is the single source of truth that keeps the slices' seams
aligned; every plan references it.

| # | Slice | Planner | Files | Gate |
|---|-------|---------|-------|------|
| 1 | Extract `reduzent_shared` | flash (pro checklist) | create `tools/reduzent_shared.py`; modify `tools/midi_bridge.py` | `python3 tools/test_midi_bridge.py` passes |
| 2 | Model + save format | flash | create `tools/looper.py` (model + serializer), `tools/test_looper.py` | round-trip + empty-state tests |
| 3 | Loop engine (record + playback) | flash (pro review) | extend `tools/looper.py`, `tools/test_looper.py` | engine round-trip tests |
| 4 | Runtime integration (the MVP) | flash (pro review) | extend `tools/looper.py` | manual on-device pass |
| 5 | Git genesis (extra feature) | flash | extend `tools/looper.py`, `tools/test_looper.py` | commit-decision test + manual git |

Slice 5 is an extra feature: the looper works without it.

### Planner division of labour (pro vs flash)

- **Pro** wrote the spec and the interface contract below, and provides the
  checklists embedded in the slice 1 and 3 plan skeletons.
- **Flash plans as-is (no further pro touch):** slices 1 (pro checklist
  already in the plan skeleton), 2 (fully example-specified by the spec), and
  5 (mechanical subprocess + one pure commit-decision function).
- **Flash drafts, pro reviews (not authors):** slice 3 (the engine's exact
  code must encode the dense edge cases — fresh-length rule, over-record
  final-pass-wins, cancel-restores-prior-mute — where a plan bug becomes a
  subtle runtime bug the executor faithfully reproduces) and slice 4 (weak
  planners tend to write "wire up the MIDI callback" instead of exact code; the
  plan must be held to the no-placeholder rule using `midi_bridge.py` as a
  line-by-line template).
- **Residual pro work:** review of slice 3's and slice 4's plan docs. Execution
  (all five slices) runs on a weaker model, which is viable only because the
  plans are bite-sized and contain exact code and test text.

### Interface contract

Shared API pinned here so independently-planned slices agree. Slices consume
and produce exactly these names and types.

**Model** (`tools/looper.py`, slice 2):

```python
from dataclasses import dataclass, field

@dataclass
class Event:
    phase: float            # position in [0, length), master seconds
    seq: int                # monotonic, = file line order
    cmd: str                # reduzent text command; channel embedded

@dataclass
class Track:
    events: list[Event]     # kept sorted by (phase, seq)
    muted: bool = False

@dataclass
class Loop:
    length: float = 0.0                # 0.0 == "no loop"
    tracks: dict[int, Track] = field(default_factory=dict)  # channel -> Track
    anchor: float | None = None        # time.monotonic() at phase 0; None == no loop
```

**Serializer** (slice 2):

```python
def loop_to_text(loop: Loop) -> str     # deterministic; "no loop" == "length 0.0" + no events
def loop_from_text(text: str) -> Loop   # raises ValueError on malformed input
def save_loop(path: str, loop: Loop) -> None
def load_loop(path: str) -> Loop
```

**Engine** (slice 3; the runtime in slice 4 drives it, nothing else):

```python
class Engine:
    loop: Loop
    rate: float                            # live-only, 0.25..4.0, default 1.0

    def phase(self, now: float) -> float | None    # ((now - anchor) * rate) % length; None if no loop
    def toggle(self, now: float) -> list[str]      # space: start/stop a take; returns live commands to emit
    def cancel(self) -> None                        # 'd' during a take
    def delete_track(self, ch: int) -> list[str]   # 'd' idle; returns live commands (e.g. ["noff <ch>"])
    def toggle_mute(self, ch: int) -> list[str]    # 'x'; returns live commands
    def set_rate(self, rate: float) -> None
    def halt(self) -> list[str]                     # 'p'; returns ["panic"]
    def resume(self, now: float) -> None           # 'p' again
    def due(self, now: float) -> list[Event]       # scheduler poll: due events in (phase, seq) order
    def record(self, cmd: str, ch: int, note: int | None, now: float) -> None  # stamp MIDI into the take
    @property
    def recording(self) -> bool                    # a take is in progress
```

Semantics for each name come from the sections above (Recording, Playback
scheduler, Hotkeys); the contract fixes names and types only. `record` receives
the post-override reduzent command, its channel, and its note number (or `None`
for non-note commands) — the runtime does `midi_to_command` + override and
forwards live, exactly as `midi_bridge` does today.
