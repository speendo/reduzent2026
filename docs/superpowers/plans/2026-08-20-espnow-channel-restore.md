# ESP-NOW Channel Restore on Settings Exit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the ESP-NOW WiFi channel after leaving settings mode so `esp_now_send()` stops failing with `E (…) ESPNOW: Peer channel is not equal to the home channel, send fail!` (and `rc=12390` = `0x3066` = `ESP_ERR_ESPNOW_CHANNEL`).

**Architecture:** Centralize the channel restore in `wifi_ap_stop()` — the single place every settings→live transition already passes through. It now takes the live channel and re-applies it after returning to STA mode, because a fresh STA start resets the radio to the default channel (1) while the broadcast peer is re-added with `cfg.espnow_channel` (13). Both `exit_settings_mode()` call sites pass `cfg.espnow_channel` and drop their now-redundant `WiFi.mode(WIFI_OFF)`. No pure logic changes; verification is compile + hardware.

**Tech Stack:** C (Arduino framework), PlatformIO (`leaf`/`controller` envs), ESP32-C3, WiFi STA/AP + ESP-NOW.

**Specs:**
- `docs/superpowers/specs/2026-08-19-settings-mode-design.md` — settings/live mode + `wifi_ap.h` API (updated in Task 2 with the channel-restore requirement).
- `docs/research-notes.md` — the ESP-NOW home-channel gotcha is recorded there in Task 2.

## Global Constraints

- Work on branch **`feature/settings-mode`** (current branch; this bug is a settings-mode defect). Commit per task; never push.
- **The working tree has unrelated uncommitted changes** (`src/leaf_main.cpp` LEAF_DEBUG instrumentation, `platformio.ini`, `scripts/parasol_setup.py`, `.vscode/*`). Re-read every file immediately before editing; only stage the files this plan touches. Do not modify the unrelated work.
- Hardware envs (`leaf`, `controller`, `controller-classic`) cannot run `pio test` (the test binary links framework `main.cpp` without `setup()`/`loop()`); use `pio run -e leaf -e controller` for compile checks. `controller-classic` **cannot build**: it predates the parasol integration and has no `lib_deps` (fails at `#include <ESPAsyncWebServer.h>`); this is pre-existing and out of scope here — noted in Backlog. `pio test -e native` is unaffected (no pure logic changes).
- `esp_wifi_set_channel()`'s return value must be checked and logged — a silently ignored failure is exactly how this bug hid.
- Root-cause rule (from the SDK header `esp_now.h`): a peer's `channel` field "must be set as the channel that station or softap is on". The country code and `esp_wifi_set_ps()` settings persist across WiFi start/stop; **the channel does not** — it resets on every fresh `esp_wifi_start()`.
- Commit messages match repo style (`fix:`, `docs:`).

## File Structure

| File | Task | Responsibility |
|------|------|---------------|
| `lib/reduzent/wifi_ap.h` | 1 | `wifi_ap_stop(channel)` re-applies the ESP-NOW channel after returning to STA |
| `src/controller_main.cpp` | 1 | `exit_settings_mode()` calls `wifi_ap_stop(cfg.espnow_channel)`; drop redundant `WiFi.mode(WIFI_OFF)`; correct `on_send` comment |
| `src/leaf_main.cpp` | 1 | `exit_settings_mode()` calls `wifi_ap_stop(cfg.espnow_channel)`; drop redundant `WiFi.mode(WIFI_OFF)`; add + register no-op `on_send` |
| `docs/research-notes.md` | 2 | Record the ESP-NOW home-channel gotcha (root cause, rule, fix) |
| `docs/superpowers/specs/2026-08-19-settings-mode-design.md` | 2 | Update `wifi_ap_stop` signature + channel-restore requirement |
| `docs/superpowers/plans/2026-08-20-espnow-channel-restore.md` | 3 | Commit this plan |

---

### Task 1: Restore the ESP-NOW channel in `wifi_ap_stop()`

**Files:**
- Modify: `lib/reduzent/wifi_ap.h:19-22`
- Modify: `src/controller_main.cpp:187-203`
- Modify: `src/leaf_main.cpp:458-477`

**Interfaces:**
- Consumes: `cfg.espnow_channel` (`uint8_t`, defaults to 13) from `controller_config_t` / `leaf_config_t` in `config.h`.
- Produces: `wifi_ap_stop(uint8_t channel)` — stops the AP, returns to STA mode, re-applies the given channel to the radio, and logs on failure. Callers invoke it as `wifi_ap_stop(cfg.espnow_channel)`.

- [x] **Step 1: Re-read the three files and confirm current state**

Run: `git -C /config/reduzent2026 status --short`
Confirm `wifi_ap_stop` currently has signature `(void)` in `lib/reduzent/wifi_ap.h`, and both `exit_settings_mode()` bodies still match the anchors below. If any anchor no longer matches (e.g. the user changed them), STOP and report — do not guess.

- [x] **Step 2: Change the `wifi_ap_stop()` signature and body**

In `lib/reduzent/wifi_ap.h`, replace lines 19-22:

```c
// Leave settings mode: stop the AP, return to STA mode for ESP-NOW, and
// re-apply the ESP-NOW channel. A fresh STA start resets the radio to the
// default channel (1); without re-applying the channel, esp_now_send fails
// with "Peer channel is not equal to the home channel" because the broadcast
// peer is re-added with channel != 1. The country code and power-save setting
// persist across start/stop; the channel does not.
// Re-init of ESP-NOW (callbacks + broadcast peer) is the caller's job.
static inline void wifi_ap_stop(uint8_t channel) {
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_STA);
    if (esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE) != ESP_OK) {
        Serial.println("set_channel failed");
    }
}
```

`Serial` is available here: `wifi_ap.h` includes `<WiFi.h>` (which pulls in Arduino), and both firmwares include `<Arduino.h>` before `wifi_ap.h`.

- [x] **Step 3: Update the controller call site**

In `src/controller_main.cpp`, `exit_settings_mode()` (currently lines 187-203), replace the first two statements:

```c
    server.end();
    wifi_ap_stop(cfg.espnow_channel);   // was: WiFi.mode(WIFI_OFF); wifi_ap_stop();
```

Delete the standalone `WiFi.mode(WIFI_OFF);` line — it is redundant because `wifi_ap_stop()` already runs `WiFi.softAPdisconnect(true)` (which itself sets mode off) before `WiFi.mode(WIFI_STA)`.

- [x] **Step 4: Update the leaf call site**

In `src/leaf_main.cpp`, `exit_settings_mode()` (currently lines 458-477), replace the first two statements:

```c
    server.end();           // stop the web server
    wifi_ap_stop(cfg.espnow_channel);   // was: WiFi.mode(WIFI_OFF); wifi_ap_stop();
```

Delete the standalone `WiFi.mode(WIFI_OFF);` line (same reason as the controller).

- [x] **Step 5: Make the leaf's send-callback registration consistent with the controller**

In `src/leaf_main.cpp`, the leaf sends heartbeats but never registers an ESP-NOW send callback (the controller registers a no-op `on_send`). This is likely benign — ESP-IDF drains its tx queue via its internal send callback regardless — but the firmwares should be uniform. Add a no-op before `on_recv`:

```c
// No-op send callback: heartbeat sends are fire-and-forget. ESP-IDF drains its
// tx queue via its internal send callback regardless; registering here keeps
// the leaf uniform with the controller and surfaces no stale-state risks.
static void on_send(const uint8_t* mac, esp_now_send_status_t status) {
    (void)mac;
    (void)status;
}
```

Register it immediately after each `esp_now_register_recv_cb(on_recv);` — in `setup()` and in `exit_settings_mode()`:

```c
    esp_now_register_send_cb(on_send);
    esp_now_register_recv_cb(on_recv);
```

Also correct the controller's misleading `on_send` comment (`src/controller_main.cpp:50-51`) — it claims the no-op is required to prevent `esp_now_send` stalling; ESP-IDF drains the queue via its internal callback, so the no-op is for uniformity, not necessity.

- [x] **Step 6: Compile-check the firmware envs**

Run: `pio run -e leaf -e controller`
Expected: both build clean, no warnings. (`controller-classic` fails at `#include <ESPAsyncWebServer.h>` due to a pre-existing missing `lib_deps` — unrelated, see Global Constraints.) If `wifi_ap_stop` still has callers with the old `(void)` signature anywhere, the build will fail with "too few arguments" — grep for `wifi_ap_stop` first if that happens.

- [x] **Step 7: Commit**

`src/leaf_main.cpp` already has unrelated uncommitted hunks (LEAF_DEBUG instrumentation). Before committing, inspect:

```bash
git -C /config/reduzent2026 diff src/leaf_main.cpp
```

Stage only this plan's hunks — use `git add -p` (accept the `exit_settings_mode` hunks) if the file mixes unrelated changes, or `git add lib/reduzent/wifi_ap.h src/controller_main.cpp` + `git add src/leaf_main.cpp` only if the leaf diff contains nothing but this plan's edits. Never stage `platformio.ini`, `scripts/parasol_setup.py`, `.vscode/*`, or the user's LEAF_DEBUG blocks. Then:

```bash
git commit -m "fix: restore ESP-NOW channel after leaving settings mode"
```

---

### Task 2: Record the gotcha in docs

**Files:**
- Modify: `docs/research-notes.md`
- Modify: `docs/superpowers/specs/2026-08-19-settings-mode-design.md`

**Interfaces:**
- Consumes: the code change from Task 1 (the new `wifi_ap_stop(uint8_t channel)` signature).
- Produces: documentation that future work re-reads; keeps the spec's `wifi_ap.h` API section truthful.

- [x] **Step 1: Add an ESP-NOW channel section to `docs/research-notes.md`**

After the existing "## 6. Settings / live mode" section, add:

```markdown
## 6a. ESP-NOW channel vs. WiFi mode switches (gotcha)

**Decision: every settings→live transition must re-apply the ESP-NOW channel.**

- ESP-NOW requires `peer.channel` to equal the WiFi radio's *current* channel
  (`esp_now.h`): "If the value is 0, use the current channel ... Otherwise, it
  must be set as the channel that station or softap is on." Otherwise
  `esp_now_send()` fails with `E (…) ESPNOW: Peer channel is not equal to the
  home channel, send fail!` (`ESP_ERR_ESPNOW_CHANNEL` = `0x3066`).
- Switching `WiFi.mode(WIFI_OFF)` → `WiFi.mode(WIFI_STA)` restarts the WiFi
  driver, which **resets the radio to the default channel (1)**. The country
  code (`wifi_set_country`) and `esp_wifi_set_ps(WIFI_PS_NONE)` persist across
  start/stop; the channel does not.
- Boot sets the channel correctly (`esp_wifi_set_channel(cfg.espnow_channel)`
  before `esp_now_init` + `esp_now_add_peer`). The settings-mode exit path
  missed this, so after every boot window (default `settings_window_sec = 30`)
  the controller keepalive / leaf heartbeat repeatedly hit the channel error.
- Fix: `wifi_ap_stop()` centralizes the restore — it re-applies
  `esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE)` after `WiFi.mode(WIFI_STA)`
  and checks the return value. Keep AP channel == ESP-NOW channel
  (`cfg.espnow_channel`) so no channel switching is ever needed between modes.
- Any future code that calls `WiFi.mode(...)` (especially OFF → STA) and then
  uses ESP-NOW must re-apply `esp_wifi_set_channel()` afterwards.
```

- [x] **Step 2: Update the settings-mode spec's `wifi_ap.h` API section**

In `docs/superpowers/specs/2026-08-19-settings-mode-design.md`, in the "WiFi AP Module" block (lines 114-136):

1. Change the prototype line to `void wifi_ap_stop(uint8_t channel);`.
2. Replace the `wifi_ap_stop()` behavior bullet with:

```markdown
- `wifi_ap_stop(channel)`: `WiFi.softAPdisconnect(true)` → `WiFi.mode(WIFI_STA)`
  → `esp_wifi_set_channel(channel, WIFI_SECOND_CHAN_NONE)`. The channel must be
  re-applied because a fresh STA start resets the radio to the default channel
  (1), and ESP-NOW sends fail ("Peer channel is not equal to the home channel")
  when `peer.channel` != the radio's current channel. ESP-NOW re-init is the
  caller's job (see below).
```

- [x] **Step 3: Commit**

```bash
git add docs/research-notes.md docs/superpowers/specs/2026-08-19-settings-mode-design.md
git commit -m "docs: record ESP-NOW home-channel gotcha"
```

---

### Task 3: Verify end-to-end

**Files:**
- Read: none (verification only)

- [x] **Step 1: Full compile check**

Run: `pio run -e leaf -e controller -e controller-classic`
Expected: all three build clean.

- [ ] **Step 2: Hardware check — leaf boot window (the exact repro from the bug report)**

Flash the leaf (`pio run -e leaf -t upload`), open the serial monitor, and let it boot with default config (`espnow_channel=13`, `settings_window_sec=30`). Expected serial output:

```
[dbg] cfg ... espnow_ch=13 window=30s
[dbg] mode: settings
leaf ready
[dbg] mode: live
[dbg] hb send rc=0 played=0 last=30s
```

**No** `E (…) ESPNOW: Peer channel is not equal to the home channel` line, and heartbeat `rc=0` (was `rc=12390`). Wait through at least one more heartbeat (~11 s later) and confirm no channel error appears.

- [ ] **Step 3: Hardware check — controller keepalive**

Flash the controller (`pio run -e controller -t upload`), boot it (30 s window), and confirm no channel error in the serial monitor and no `send failed` lines from `transmit()`.

- [x] **Step 4: Commit the plan**

```bash
git add docs/superpowers/plans/2026-08-20-espnow-channel-restore.md
git commit -m "docs: add ESP-NOW channel restore plan"
```

## Backlog

- **`controller-classic` env cannot build**: it predates the parasol integration and has no `lib_deps` (fails at `#include <ESPAsyncWebServer.h>`). Add the same `lib_deps` / `lib_ignore` / `lib_ldf_mode` as the `controller` env when the ESP32 classic controller is actually brought up.
- Defensive improvement: check the return value of `esp_wifi_set_channel()` in `setup()` (not just in `wifi_ap_stop()`) so a misconfigured channel fails loudly at boot.
