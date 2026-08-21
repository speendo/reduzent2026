# Looper Navigation & Channel UI Design

Date: 2026-08-21
Status: approved for implementation
Extends: `2026-08-17-midi-looper-design.md` (its Hotkeys and Status bar sections are superseded by this document)

## Purpose

Extend `tools/looper.py`'s terminal interface with an explicit **selected
channel** (an edit cursor), keyboard and MIDI-note navigation over the loop's
channels, named channels from config, and a right-side column that lists all
present channels with the selection highlighted. Purely host-side: no firmware
changes, no protocol changes, and recording semantics are untouched.

## Goals / non-goals

Goals:

- One explicit selection state driving `d`/`x`/`o`, settable by number keys,
  arrow keys, Tab, and a MIDI note — without playing a note on that channel.
- The selected channel is impossible to miss: bold red inverse video,
  blinking, in a dedicated right-side channel column.
- Named channels (`"channels"` map in `midi-bridge.json`) shown in the UI and
  in feedback messages; graceful degradation when the config lacks them.
- MIDI note hotkeys to start/stop recording and cycle channels (foot-pedal
  friendly), intercepted so they never sound or get recorded.

Non-goals (backlog):

- A `k` prompt to edit channels/hotkeys from inside the looper (hand-edit the
  JSON for now).
- Selection as record target or live-MIDI reroute — explicitly rejected:
  selecting must never change what playing sounds like or what a take records.
- Further MIDI hotkey actions (mute/delete/rate via notes).
- Mouse support.

## The selection (edit cursor)

- New runtime variable `selected`: a channel number or `None`.
- **Startup:** `selected` = lowest present channel (config list if set, else
  lowest tracked channel once a loop is loaded); `None` when neither is known.
- **Target precedence** for `d` (delete/cancel), `x` (mute/unmute) and `o`
  (channel silence): `selected` → `c` override → most recent note's channel.
  Until the first navigation this reproduces today's behavior exactly.
- Recording is unchanged: takes still record onto the `c` override if set,
  else lock to the first recorded note's channel. Live MIDI routing is never
  affected by selection.
- The selection persists until changed by another navigation key; loading a
  loop does not move it.

## Hotkeys (complete reference)

Keyboard — existing unless marked NEW:

| Key | Action |
|---|---|
| `space` | Start/stop a take (record/commit) |
| `d` | Delete selected channel's track; while a take: cancel it |
| `x` | Mute/unmute selected channel |
| `p` | Panic + halt playback; again resumes (tape-pause) |
| `o` | Channel silence (`noff <ch>` one-shot) |
| `+` / `-` | Playback rate up/down (0.05 step) |
| `Backspace` | Rate reset to 1.0× (**moved** — was `0`) |
| `0`–`9` | Jump to channel N (**NEW**) |
| `↑` / `↓` | Step prev/next through present channels, wrapping (**NEW**; channels are listed top-to-bottom in the column, so up/down matches the layout; `←`/`→` kept as aliases) |
| `Tab` | Cycle forward through present channels (**NEW**) |
| `c` | Channel override prompt (reroutes live MIDI + record target; unchanged) |
| `i` | Instrument prompt |
| `m` | Port menu |
| `s` | Settings mode |
| `w` | Save loop (named) |
| `r` | Load loop |
| `q` / Ctrl-C | Quit |

MIDI hotkeys (**NEW**, configured, inactive when unset):

| Match | Action |
|---|---|
| `midi_hotkeys.record` | Toggle take — same as `space` |
| `midi_hotkeys.cycle` | Select next present channel — same as `Tab` |

Matched notes are **intercepted**: not forwarded to the leaves, not recorded
into the take, and they do not poison the first-note-channel lock of a take.
Unmatched notes behave exactly as today. Prompts (`c i m s w r`) already
disable the MIDI callback, so hotkeys cannot fire mid-prompt.

## Config

Both keys live in the existing `~/.config/reduzent/midi-bridge.json`
(`reduzent_shared.load_settings`/`save_settings`), hand-edited:

```json
{
  "channels": { "0": "kick", "1": "snare", "5": "bass-flute" },
  "midi_hotkeys": {
    "record": {"channel": 15, "note": 60},
    "cycle":  {"channel": 15, "note": 62}
  }
}
```

- `"channels"` maps channel number → display name. JSON keys are strings;
  values are sanitized to a single short line for display. This map defines
  the **present channels**: what arrows/Tab step through and what the column
  lists.
- `"midi_hotkeys"` maps action name → `{channel, note}` integers.

### Degradation ladder (graceful, always)

| Config state | Behavior |
|---|---|
| File missing/unreadable | No names, no present list → present = tracked channels of the loaded loop; navigation works over those |
| `"channels"` absent | Same as above |
| Malformed entries (bad type, ch >15, empty name) | Warn once, keep valid entries; all invalid → treated as absent |
| Channel without usable name | Displayed as its number |
| `"midi_hotkeys"` absent/malformed entry | That hotkey inactive; space/Tab still work |

Zero-config behavior therefore equals today's looper plus navigation over
existing tracks; nothing new requires the file.

## Right-side channel column

- All present channels listed top-right, one per line, sorted by channel
  number: `<ch>: <name>` (or just `<ch>` when unnamed) in a fixed-width cell
  so the column never jumps as selection moves between short and long names —
  dim = no track · bright = track · muted marker (`*`) = muted ·
  **bold red inverse, blinking = selected**.
- Console output lines are truncated to leave the column free; the panel
  repaints on the existing redraw tick (~0.15 s), which also drives the blink.
- Degrades gracefully: terminal too narrow → no panel; more channels than fit
  vertically → last line reads `+n more`.
- The line-2 inline channel strip is removed (the column replaces it); line 2
  keeps `sel:<name-or-number>` plus instrument and the help line, which gains
  the new keys (`0-9 ch  ←→/tab nav  ⌫ rate1`).

## Error handling / edge cases

- Digit jump to a channel with no track: allowed; `d`/`x` then report
  "nothing on ch N".
- Arrows/Tab with an empty present-channel list: one-line hint, no state
  change.
- Arrow keys arrive as 3-byte escape sequences in raw mode; the runtime
  drains the trailing bytes with a short `select` timeout.
- Terminal resize: width/height re-read on every redraw tick.
- A hotkey note equal to a musical note is a configuration choice; documented
  as such (interception means that note can't be played live while configured).

## Testing

Native unit tests extend `tools/test_looper.py` (pure logic, fake clock):

- Present-channel resolution (config → fallback to tracks → empty) and sort.
- Next/prev stepping with wrap-around; digit mapping; startup lowest-channel
  init.
- Target resolution precedence (selected → override → last channel).
- Config parsing/validation for `"channels"` and `"midi_hotkeys"`,
  including malformed input and the warn-once path.
- Hotkey match → action dispatch; unmatched notes pass through untouched.
- Column line rendering per state (ANSI/markup assertions); overflow marker.

Manual on-device pass: arrow/tab/digit feel, blink cadence, layout at several
terminal widths, foot-pedal hotkeys end-to-end.

## Backlog

- `k` prompt to edit/save channels and hotkeys from within the looper.
- More MIDI hotkey actions (mute/delete/rate).
- Revisit selection-as-record-target if the edit-cursor-only rule proves
  awkward in practice.
