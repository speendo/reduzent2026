# midi_bridge.py Terminal UX

## Goal

Improve the terminal experience of `tools/midi_bridge.py` without degrading
MIDI-to-serial latency. The hot path (`on_message` callback) must remain
unchanged in its I/O characteristics.

## Changes

### 1. Fix line breaks in raw terminal mode

**Problem:** `print(cmd, flush=True)` uses `\n` which in raw terminal mode
(`tty.setraw`) moves the cursor down but not to column 0. Successive MIDI
commands appear concatenated on the same visual line.

**Fix:** Replace `print(cmd, flush=True)` with
`sys.stdout.write(cmd + "\r\n")`. The `\r` returns to column 0.

**Latency impact:** +1 byte in string concatenation, negligible vs. the
serial write that dominates the path.

### 2. Persistent status bar (minimal style)

**Problem:** Hotkeys (`m`, `s`, `q`) are shown once at startup, then buried
by the scrolling MIDI log. Users forget what keys are available.

**Design:** Two status lines at the bottom of the terminal, prefixed with
`▸` in ANSI bold cyan. No box-drawing characters, no Unicode borders.

```
 ▸ USB MIDI Keyboard → /dev/ttyUSB0 @ 115200
 ▸ ch: 0 (MIDI)  inst: --   m menu  s settings  c ch  i inst  q quit
```

**Implementation:** Use ANSI scroll region (`\033[1;{N}r`) to reserve the
bottom 2 lines. The log scrolls in the upper region; the status bar stays
fixed. On state changes (override toggled, port switched), clear and redraw
the two status lines using `\033[{row};1H\033[2K` (move + clear line).

On exit, restore full terminal with `\033[r` (reset scroll region).

**Latency impact:** Status bar redraws happen in the main loop (select
timeout path), not in `on_message`. Zero impact on MIDI forwarding.

### 3. Channel override

**Problem:** Some use cases require routing all MIDI to a single output
channel regardless of the input channel (e.g., controlling a specific leaf
during setup).

**Design:**
- State variable: `override_ch: Optional[int] = None`
- Hotkey `c`: restore terminal, prompt `Output channel [0-15, empty=clear]: `,
  parse input, set `override_ch`, re-enter raw mode.
- In `on_message`: `ch = override_ch if override_ch is not None else msg.channel`
- Status bar shows `ch: 3 (override)` when active, `ch: 0 (MIDI)` when passthrough.

**Latency impact:** Single `if` + variable lookup. ~50ns, vs. µs-range
serial write.

### 4. Instrument override

**Problem:** Same as channel — need to force a specific program on the
leaves without waiting for the DAW/sender to emit a program change.

**Design:**
- State variable: `override_inst: Optional[int] = None`
- Hotkey `i`: prompt `Program [0-127, empty=clear]: `, set `override_inst`.
- On first set (transition from None to a value): immediately send
  `g <ch> <inst>` to the serial port so leaves switch without waiting.
- In `on_message`: for `program_change` messages, substitute
  `msg.program` with `override_inst` if set.
- Status bar shows `inst: 5` when active, `inst: --` when passthrough.

**Latency impact:** Single `if` on `program_change` path only. Other
message types skip it entirely.

### 5. Heartbeat coloring

**Problem:** Heartbeat lines from the controller (`hb <mac> played=N last=Ns`)
blend in with regular MIDI log output and tx confirmations.

**Design:** In the main loop's serial echo path, check
`if data.startswith(b"hb ")`. If true, wrap the heartbeat text in ANSI
dim/cyan before writing to stdout. All other serial output stays default color.

**Latency impact:** This runs in the main loop's serial read, not in
`on_message`. Even if it were, `bytes.startswith()` is a single C-level
comparison. Negligible.

## Hotkey summary

| Key | Action |
|-----|--------|
| m   | Open port menu (switch MIDI input / serial port) |
| s   | Send settings mode to leaf |
| c   | Override output channel |
| i   | Override instrument |
| q / Ctrl-C | Quit |

All hotkeys are displayed in the status bar.

## What does NOT change

- `midi_to_command()` pure function — untouched
- Settings load/save logic — untouched
- Thread model and locking — untouched
- Serial I/O, ESP-NOW — untouched
- Argparse (still manual `sys.argv` parsing)
- `open_connections()`, `resolve_settings()`, `menu_choice()` — unchanged
- Test file `test_midi_bridge.py` — no changes needed (tests pure functions
  only)

## Latency analysis

The MIDI-to-serial hot path (`on_message` callback, background thread):

1. `midi_to_command(msg)` — pure, unchanged
2. `s.write((cmd + "\n").encode())` — serial I/O, dominant latency (~µs–ms)
3. `sys.stdout.write(cmd + "\r\n")` — console output (unless `--quiet`)

Changes touching this path:
- `\r\n` vs `\n`: +1 byte in concat, negligible
- Channel/instrument override: single `if` per message, ~50ns

Changes NOT in this path:
- Status bar redraw: main loop only
- Heartbeat coloring: main loop serial read only

No new I/O, allocations, or syscalls added to `on_message`.

## Files touched

- `tools/midi_bridge.py` — all changes in this file
- `tools/test_midi_bridge.py` — no changes (tests pure functions only)

## Backlog

- Colored MIDI log output (green for note_on, red for note_off, etc.)
  — deferred to avoid complexity in this slice
- curses-based full-screen TUI — overkill for current needs
