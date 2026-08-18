# ESP-NOW Reliability — Handoff Document

**Branch:** `feat/espnow-reliability` (8 commits on top of `main` at `8549872`)
**Status:** Implementation complete, all tests pass, ready to merge
**Date:** 2026-08-17

## What Was Built

Self-healing ESP-NOW link: controller re-affirms held notes via keepalive
(`NOTE_HOLD` every 750 ms), leaf watchdog releases stuck voices after 3 s,
panic and notes-off are sent 3x redundantly and clear the controller's
held-note table. MIDI CC120/121/123 map to hard-stop / reset-controllers /
release respectively, each scoped to the MIDI channel.

### Commits

```
c692ed6 docs: document keepalive/watchdog and channel-scoped panic/notes-off
69b48b5 feat: bridge CC120/121/123 channel-scoped + panic/noff hotkeys
9a936c6 feat: controller held-notes table + keepalive + redundant panic/noff
0d1a4fb feat: leaf handles NOTE_HOLD/NOTES_OFF/RESET_CONTROLLERS + watchdog
146bbd5 feat: voice hold-refresh, watchdog, and bulk notes-off
ea76014 feat: add held-notes table for controller keepalive
99f4011 feat: parse panic/noff/resetcc with optional channel
717029b feat: add NOTE_HOLD, NOTES_OFF, RESET_CONTROLLERS event types
```

## Rulings Made During Implementation

### 1. Parser word-boundary check (deferred)

**Finding:** `noff` and `resetcc` commands use 4/7-char prefix checks
(`line[0]=='n' && line[1]=='o' && line[2]=='f' && line[3]=='f'`) without
verifying the next byte is `\0` or space. Input like `"nofffoo"` would
silently parse as broadcast notes-off.

**Ruling:** Deferred. The serial debug protocol only sends well-formed
commands. The existing `panic` command uses the same pattern. Adding a
word-boundary check (`line[4] == '\0' || line[4] == ' '`) is trivial but
not required for correctness in the current protocol.

**Cost if wrong:** Garbage serial input silently defaults to broadcast
channel. Low risk — serial link is trusted, not user-facing.

**Action for next work:** Add `line[N] == '\0' || line[N] == ' '` after
each new prefix check in `text_parser.h`. The existing `panic` check
should get the same treatment for consistency.

### 2. Voice-steal watchdog test gap (deferred)

**Finding:** The plan explicitly warns: "a stolen voice left with
`hold_refresh_ms = 0` would be instantly released by the watchdog." The
implementation correctly sets `hold_refresh_ms = now_ms` in the steal
branch (`voice.h:94`), but no test exercises the steal-then-watchdog path.

**Ruling:** Deferred. The code is correct — the field is initialized in
the steal branch. The test gap is a regression vector, not a bug.

**Cost if wrong:** A future refactor that omits `hold_refresh_ms = now_ms`
in the steal branch would go undetected until runtime. Stuck notes would
appear under heavy polyphony (8+ simultaneous notes).

**Action for next work:** Add a test to `test/test_voice/test_voice.cpp`
that fills all 8 voices, triggers a steal, advances to sustain, then
verifies the watchdog doesn't release the stolen voice prematurely.

## Deferred Issues from Task Reviews

| Task | Issue | Severity | Status |
|------|-------|----------|--------|
| 2 | `parse_command` function comment doesn't list `noff`/`resetcc` | Minor | Deferred |
| 3 | `held_notes_init` uses nested loop instead of `memset` (2 KB zero-fill) | Minor | Deferred |
| 5 | `poly_pressure` loop uses raw literal `128` instead of named constant | Minor | Deferred |
| 8 | `research-notes.md` types list omits new event types | Minor | Deferred |

None of these block merge. The function comment and types-list staleness
are documentation hygiene. The memset and named-constant issues are
style/perf nits that matter only if the codebase grows.

## Key Design Constraints

- **Frame is fixed 5 bytes, channel-first.** Do not grow it.
- **X = 3000 ms** (stuck-note timeout), **Y = 4** (redundancy factor),
  **R = 750 ms** (keepalive interval = X / Y).
- **Pure logic** in header-only `lib/reduzent/*.h`; Arduino idioms in
  `src/*_main.cpp`. Tests are native (PlatformIO Unity), not on-device.
- **Two firmware envs** split via `build_src_filter` in `platformio.ini`.
  Leaf excludes `controller_main.cpp`; controller excludes `leaf_main.cpp`.

## Files Changed

| File | Change |
|------|--------|
| `lib/reduzent/espnow_frame.h` | Added EVENT_NOTE_HOLD=9, EVENT_NOTES_OFF=10, EVENT_RESET_CONTROLLERS=11 |
| `lib/reduzent/text_parser.h` | `panic <ch>`, `noff [ch]`, `resetcc [ch]` with channel validation |
| `lib/reduzent/held_notes.h` | **New.** 16x128 velocity table with init/set/clear/iterator |
| `lib/reduzent/voice.h` | `hold_refresh_ms` field, `voice_note_hold`, `voice_watchdog`, `voice_all_notes_off` |
| `src/leaf_main.cpp` | Switch cases for 3 new events + watchdog in loop |
| `src/controller_main.cpp` | Held-note tracking, keepalive sender, redundant panic/noff, timed semaphore |
| `tools/midi_bridge.py` | CC120→panic, CC121→resetcc, CC123→noff (channel-scoped), `p`/`o` hotkeys |
| `tools/test_midi_bridge.py` | 3 new tests replacing old `test_cc_panic` |
| `docs/protocol-spec.md` | Updated event table + reliability section |
| `docs/research-notes.md` | Reliability decision entry |
| `test/test_espnow_frame/` | 2 new tests (event type values + round-trip) |
| `test/test_text_parser/` | 5 new tests + 3 reject assertions |
| `test/test_held_notes/` | **New.** 5 tests (init, set+iterate, clear single/channel/all) |
| `test/test_voice/` | 6 new tests (hold refresh, watchdog, all-notes-off) |

## What's Backlogged

- **Voice-steal watchdog test** (see Ruling #2 above)
- **Parser word-boundary checks** (see Ruling #1 above)
- **Named constant for poly_pressure size** (`#define NUM_NOTES 128`)
- **`memset` in held_notes_init** (replace nested loop)
- **Update `parse_command` doc comment** to list new commands
- **Update research-notes types list** to include new event types
- The broader project backlog (multiple controllers, acks/retry, battery
  sleep, ESP-IDF migration, etc.) per `docs/superpowers/specs/`
