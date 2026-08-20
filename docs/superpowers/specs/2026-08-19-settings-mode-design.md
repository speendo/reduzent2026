# Settings/Live Mode + WiFi AP Design

Date: 2026-08-19
Status: draft

## Purpose

Implement the settings/live mode state machine and WiFi AP functionality that
enables parasol web configuration on both leaves and the controller. This is
Steps 2-3 of the parasol integration roadmap (Step 1: NVS config foundation is
already specced).

## Scope

- Shared mode state machine (lib/reduzent/mode.h)
- WiFi AP start/stop (lib/reduzent/wifi_ap.h)
- Leaf firmware: handle EVENT_ENTER_SETTINGS, mode checks in loop()
- Controller firmware: settings serial command, mode checks in loop()
- parasol integration via lib_deps (Step 4, mentioned here for context)

## Dependencies

- Step 1: NVS config foundation (config.h, config_parser.h) — prerequisite
- parasol library (https://github.com/speendo/parasol) — for Step 4
- ESPAsyncWebServer + AsyncTCP — required by parasol

## Design

### Mode State Machine

**File:** `lib/reduzent/mode.h` (header-only, like other lib modules)

```c
typedef enum { MODE_LIVE, MODE_SETTINGS } device_mode_t;

typedef struct {
    device_mode_t mode;
    uint32_t      settings_start_ms;   // millis() when settings entered
    uint32_t      settings_window_ms;  // timeout duration (default 30000)
    uint8_t       client_count;        // WiFi AP clients currently connected
    uint32_t      grace_start_ms;      // millis() when grace period started; 0 = not in grace
    bool          exit_requested;      // set by parasol "leave settings" action
} mode_state_t;

#define MODE_GRACE_MS 7000  // grace period after last client disconnects

void     mode_init(mode_state_t* s, uint32_t settings_window_ms);
void     mode_enter_settings(mode_state_t* s, uint32_t now);
void     mode_exit_settings(mode_state_t* s);
void     mode_set_clients(mode_state_t* s, uint8_t count, uint32_t now);
void     mode_request_exit(mode_state_t* s);
bool     mode_tick(mode_state_t* s, uint32_t now);  // returns true if mode changed
bool     mode_is_settings(const mode_state_t* s);
```

**Behavior:**
- `mode_init()`: Sets mode to MODE_LIVE, stores timeout duration, zeroes client
  count and grace state.
- `mode_enter_settings()`: Sets mode to MODE_SETTINGS, records start time,
  clears grace and exit request.
- `mode_exit_settings()`: Sets mode to MODE_LIVE, clears grace and exit request.
- `mode_set_clients()`: Called from WiFi AP event handlers when a station
  connects or disconnects. When the last client disconnects (`prev > 0 && count
  == 0`), starts the 7-second grace period. If a client reconnects during grace,
  cancels it.
- `mode_request_exit()`: Sets `exit_requested` flag (triggered by parasol
  `_leave_settings` switch in the UI).
- `mode_tick()`: The core timer logic:
  1. If `exit_requested` → exit immediately (parasol checkbox)
  2. If clients connected (`client_count > 0`) → pause (stay indefinitely)
  3. If grace period active → count down; exit when grace expires
  4. Otherwise → count down the main timeout; exit when it expires
- `mode_is_settings()`: Simple mode check

**Timeout pausing:** The settings timeout only counts time when no WiFi clients
are connected. Once a phone/laptop connects to the AP, the timer pauses and the
device stays in settings mode indefinitely. This prevents the device from
timing out while the user is actively configuring it.

**Grace period:** When the last client disconnects (e.g., phone goes to sleep,
WiFi glitch), a 7-second grace period starts. If the user reconnects within that
window, they resume where they left off. If the grace expires, the device
returns to live mode. This handles accidental disconnects without keeping
settings mode open forever.

**Leave settings switch:** The parasol UI includes a `_leave_settings` switch
(underscore prefix = internal, not persisted to NVS). When the user checks it
and clicks Save, the save callback sets `exit_requested`, and the next
`mode_tick()` exits to live. This gives the user an explicit "I'm done" action.

**Boot behavior differs by role:**
- **Leaf:** after `mode_init()`, if `cfg.settings_window_sec > 0`, call
  `mode_enter_settings()` immediately (the boot window), then `mode_tick()`
  auto-exits to live when it expires. `0` = boot straight to live. This gives
  the user a 30s window to connect to the AP and configure the leaf via parasol
  without needing a controller present.
- **Controller:** boots straight to `MODE_LIVE`. Enter settings via serial
  `settings` command (broadcasts `EVENT_ENTER_SETTINGS` to leaves) or when the
  controller itself receives the event.

**Why header-only:** Consistent with existing lib/reduzent modules (envelope.h,
voice.h, etc.). Small footprint, no linking issues.

### WiFi AP Module

**File:** `lib/reduzent/wifi_ap.h` (header-only)

```c
void wifi_ap_start(const char* ssid, uint8_t channel);
void wifi_ap_stop(void);
void wifi_set_country(const char* country_code);
```

**Behavior:**
- `wifi_ap_start()`: `esp_now_deinit()` → `WiFi.mode(WIFI_AP)` →
  `WiFi.softAP(ssid, NULL, channel)`. Deinit ESP-NOW *before* switching modes;
  the recv callback will no longer fire once deinit'd.
- `wifi_ap_stop()`: `WiFi.softAPdisconnect(true)` → `WiFi.mode(WIFI_STA)`.
  ESP-NOW re-init is the caller's job (see below).
- `wifi_set_country()`: Calls `esp_wifi_set_country_code()`. Must run *after*
  `WiFi.mode()` (the WiFi stack is initialized there); the C3's default
  "world-safe" country code (`01`) blocks active use of channel 13.

All WiFi mode switches run in `loop()` task context, never in the ESP-NOW recv
callback (ISR/task context) — the callback only flips a flag / sets mode state.

**ESP-NOW reinit:** When exiting settings mode, ESP-NOW must be re-initialized:
`esp_now_init()` + re-register callbacks + re-`esp_now_add_peer()` (broadcast).
This reinit logic lives in the firmware (leaf_main.cpp, controller_main.cpp),
not in wifi_ap.h, because each firmware registers different callbacks.

### Leaf Firmware Changes

**File:** `src/leaf_main.cpp`

1. Add includes: `mode.h`, `config.h`, `<esp_event.h>`
2. Add static state: `static mode_state_t dev_mode;`, `static volatile bool leave_settings_request = false;`
3. In `setup()`:
   - Call `config_defaults(&cfg)` + `config_load("leaf_cfg", &cfg)`
   - Replace hardcoded `#define`s with `cfg.*` fields
   - Call `mode_init(&dev_mode, cfg.settings_window_sec * 1000)`
   - Call `mode_boot()` to enter settings at boot if window > 0 (leaf boot window)
   - Set WiFi country code: `wifi_set_country("EU")`
4. In `on_recv()`:
   - Add `case EVENT_ENTER_SETTINGS:` that enters settings only when the frame
     targets this leaf: `frame.note == 0xFF || frame.note == cfg.node_id`.
     MVP: the controller broadcasts (0xFF) and all leaves enter; targeted
     (`settings <id>`) works once `node_id` is assigned.
5. In `loop()`:
   - Check `leave_settings_request` → call `mode_request_exit()` if set
   - Add `mode_tick(&dev_mode, now)` check
   - If mode changed to settings: silence audio, then call `wifi_ap_start()`
   - If mode changed to live: re-init audio, then `wifi_ap_stop()` + reinit ESP-NOW
6. In settings mode, `loop()` must NOT:
   - render audio — skip the render dispatch; `ledcWrite` all output channels 0;
     stop the 1-bit `mix_timer` ISR if active
   - call `send_heartbeat()` — ESP-NOW is deinit'd, the send would fail
   - `solenoid_tick` and `voice_watchdog` may keep running (no new input arrives)
7. Add `settings_window_sec` and `node_id` to `leaf_config_t` in config.h
   (promoted from the config spec's "Future settings"; spec updated accordingly)
8. WiFi AP event handlers: register `WIFI_EVENT_AP_STACONNECTED` and
   `WIFI_EVENT_AP_STADISCONNECTED` handlers in `enter_settings_mode()` that call
   `mode_set_clients(&dev_mode, WiFi.softAPgetStationNum(), millis())`.
9. parasol save callback: wrap `parasol_save_leaf_to_nvs()` to check the
   `_leave_settings` switch (`prsl_get("_system._leave_settings")`) and set
   `leave_settings_request = true` before saving. Register via
   `prsl_init(&server, leaf_save_with_leave, ...)`.

### Controller Firmware Changes

**File:** `src/controller_main.cpp`

1. Add includes: `mode.h`, `config.h`, `<esp_event.h>`
2. Add static state: `static mode_state_t dev_mode;`, `static volatile bool leave_settings_request = false;`
3. In `setup()`:
   - Call `config_defaults(&cfg)` + `config_load("ctrl_cfg", &cfg)`
   - Replace hardcoded `#define ESP_NOW_CHANNEL` with `cfg.espnow_channel`
   - Call `mode_init(&dev_mode, cfg.settings_window_sec * 1000)`
   - Do NOT call `mode_boot()` — controller boots straight to live
   - Set WiFi country code: `wifi_set_country("EU")` (after `WiFi.mode()`)
4. In `handle_line()`:
   - The `settings` command *already* transmits `EVENT_ENTER_SETTINGS` via the
     `default:` case (controller_main.cpp:77-79). Add: also call
     `mode_enter_settings(&dev_mode, millis())` so the controller enters its
     own settings mode.
   - Add `cfgget`/`cfgset`/`cfgsave`/`cfgreset` command handling (from Step 1)
5. In `loop()`:
   - Check `leave_settings_request` → call `mode_request_exit()` if set
   - Add `mode_tick(&dev_mode, now)` check
   - If mode changed to settings: call `wifi_ap_start(ssid, cfg.espnow_channel)`
   - If mode changed to live: call `wifi_ap_stop()` + reinit ESP-NOW
   - In settings mode, skip `send_keepalive()` — ESP-NOW is down
6. Add `settings_window_sec` to `controller_config_t` in config.h
7. WiFi AP event handlers: same pattern as leaf — register
   `WIFI_EVENT_AP_STACONNECTED`/`WIFI_EVENT_AP_STADISCONNECTED` handlers in
   `enter_settings_mode()` that call `mode_set_clients()`.
8. parasol save callback: same pattern as leaf — wrap
   `parasol_save_controller_to_nvs()` to check `_leave_settings` switch and set
   `leave_settings_request`. Register via
   `prsl_init(&server, ctrl_save_with_leave, ...)`.

### Text Parser Extension

**File:** `lib/reduzent/text_parser.h`

The `settings` command is already parsed (EVENT_ENTER_SETTINGS). No changes
needed for the basic flow. The controller's `handle_line()` will process
the frame and call `mode_enter_settings()`.

### WiFi Channel Strategy

- ESP-NOW uses channel 13 (hardcoded, will become configurable via config)
- AP uses the same channel as ESP-NOW (cfg.espnow_channel)
- Country code set to "EU" (or configurable) to enable channel 13
- No channel switching needed between modes — same channel for both

### parasol Integration (Step 4, for context)

Not detailed here — see `docs/superpowers/specs/2026-08-19-parasol-integration-design.md`.
Key interplay with this plan: parasol groups/fields are registered and
`prsl_init`'d exactly once; the settings-mode entry/exit calls in this plan
(re)start / stop the parasol web server.

### SSID Naming Convention

- Leaf: `reduzent-leaf-<node_id>` (e.g., `reduzent-leaf-0`)
- If `node_id == 255` (unassigned), fall back to a MAC-derived suffix
  (e.g., `reduzent-leaf-AB12`) so every device still gets a unique AP name.
- Controller: `reduzent-controller`
- No password for MVP (open AP for easy configuration)

### DNS and Web Access

- **mDNS:** After `wifi_ap_start()`, call `MDNS.begin("instrument")` on both
  leaf and controller. This publishes `instrument.local` on the local subnet,
  allowing users to type `instrument.local` instead of `192.168.4.1`.
- **Root redirect:** `server.on("/", HTTP_GET, [](AsyncWebServerRequest *r){
  r->redirect("/settings"); });` — redirecting `192.168.4.1` to the settings
  page avoids the blank `/` response.

These are added in `enter_settings_mode()` after the WiFi AP starts but
before `prsl_start()`.

### Files

| File | Action | Purpose |
|------|--------|---------|
| `lib/reduzent/mode.h` | Create | Shared state machine |
| `lib/reduzent/wifi_ap.h` | Create | WiFi AP start/stop |
| `src/leaf_main.cpp` | Modify | Add mode checks, EVENT_ENTER_SETTINGS handler |
| `src/controller_main.cpp` | Modify | Add mode checks, settings command |
| `lib/reduzent/config.h` | Modify | Add settings_window_sec + node_id to config structs |
| `docs/nvs-config-spec.md` | Modify | Promote node_id + settings_window_sec from Future settings |
| `platformio.ini` | Modify | Add parasol + ESPAsyncWebServer dependencies |

### Integration with config.h (Step 1)

> **Done in Step 1 (NVS config foundation plan).** The fields below are already
> present in `leaf_config_t` / `controller_config_t` with defaults and test
> assertions; the settings-mode plan only verifies them.

Add to leaf_config_t:
```c
uint8_t  node_id;             // 0-254, 255 = unassigned
uint16_t settings_window_sec; // 0-300, default 30
```

Add to controller_config_t:
```c
uint16_t settings_window_sec;  // 0-300, default 30
```

Update config_defaults() to set these defaults (done in Step 1). These two keys
move from the config spec's "Future settings" into the active structs —
`docs/nvs-config-spec.md` is updated as part of that change.

## Testing

1. **Unit tests** (native build): Test mode state machine logic
   - Test mode_init sets MODE_LIVE
   - Test mode_init with window 0 stays LIVE at boot
   - Test mode_init with window > 0 enters settings at boot (leaf boot window)
   - Test mode_enter_settings switches to MODE_SETTINGS
   - Test mode_tick timeout triggers exit
   - Test mode_is_settings returns correct state
   - Test mode_set_clients: client connects → timeout pauses
   - Test mode_set_clients: last client disconnects → grace period starts
   - Test mode_set_clients: client reconnects during grace → grace cancelled
   - Test mode_tick: grace period expires → exit
   - Test mode_request_exit: sets flag, next tick exits

2. **Integration test** (hardware): Leaf boots → settings mode for 30s → WiFi
   AP visible → connect phone → verify parasol UI → phone disconnects → 7s
   grace → back to live mode. Controller boots to live; type `settings` in
   serial monitor to enter settings mode.

3. **Manual test**:
   - Leaf: boot → AP appears → connect phone → parasol UI loads → toggle
     `_leave_settings` + Save → exits to live
   - Controller: type `settings` in serial monitor → enters settings mode,
     broadcasts to leaves → type `settings` again to re-enter if needed
   - `settings <id>` targets a single leaf (requires node_id assigned)

## Backlog

- WiFi AP password configuration
- STA mode for shared network configuration
- Multiple controller support
- parasol image upload (OTA)
- Settings-mode trigger via MIDI (not just serial)
