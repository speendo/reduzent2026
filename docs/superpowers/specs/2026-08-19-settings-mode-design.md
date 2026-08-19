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
} mode_state_t;

void     mode_init(mode_state_t* s, uint32_t settings_window_ms);
void     mode_enter_settings(mode_state_t* s, uint32_t now);
void     mode_exit_settings(mode_state_t* s);
bool     mode_tick(mode_state_t* s, uint32_t now);  // returns true if mode changed
bool     mode_is_settings(const mode_state_t* s);
```

**Behavior:**
- `mode_init()`: Sets mode to MODE_LIVE, stores timeout duration
  (`settings_window_ms` comes from `cfg.settings_window_sec * 1000`)
- `mode_enter_settings()`: Sets mode to MODE_SETTINGS, records start time
- `mode_exit_settings()`: Sets mode to MODE_LIVE
- `mode_tick()`: If in MODE_SETTINGS and timeout expired, calls exit_settings()
  and returns true. Otherwise returns false.
- `mode_is_settings()`: Simple mode check

**Boot behavior differs by role:**
- **Controller:** after `mode_init()`, if `cfg.settings_window_sec > 0`, call
  `mode_enter_settings()` immediately (the boot window), then `mode_tick()`
  auto-exits to live when it expires. `0` = boot straight to live.
  Matches `docs/config-spec.md` ("Boot → Settings for a short window") and the
  controller column of `settings_window_sec` in `docs/nvs-config-spec.md`.
- **Leaf:** boots straight to `MODE_LIVE`; enters settings only on
  `EVENT_ENTER_SETTINGS`. The leaf's `settings_window_sec` is the timeout back
  to live after that trigger.

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

1. Add includes: `mode.h`, `config.h`
2. Add static state: `static mode_state_t dev_mode;`
3. In `setup()`:
   - Call `config_defaults(&cfg)` + `config_load("leaf_cfg", &cfg)`
   - Replace hardcoded `#define`s with `cfg.*` fields
   - Call `mode_init(&dev_mode, cfg.settings_window_sec * 1000)`
   - Set WiFi country code: `wifi_set_country("EU")`
4. In `on_recv()`:
   - Add `case EVENT_ENTER_SETTINGS:` that enters settings only when the frame
     targets this leaf: `frame.note == 0xFF || frame.note == cfg.node_id`.
     MVP: the controller broadcasts (0xFF) and all leaves enter; targeted
     (`settings <id>`) works once `node_id` is assigned.
5. In `loop()`:
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

### Controller Firmware Changes

**File:** `src/controller_main.cpp`

1. Add includes: `mode.h`, `config.h`
2. Add static state: `static mode_state_t dev_mode;`
3. In `setup()`:
   - Call `config_defaults(&cfg)` + `config_load("ctrl_cfg", &cfg)`
   - Replace hardcoded `#define ESP_NOW_CHANNEL` with `cfg.espnow_channel`
   - Call `mode_init(&dev_mode, cfg.settings_window_sec * 1000)`
   - If `cfg.settings_window_sec > 0`, call `mode_enter_settings()` at boot
     (boot window)
   - Set WiFi country code: `wifi_set_country("EU")` (after `WiFi.mode()`)
4. In `handle_line()`:
   - The `settings` command *already* transmits `EVENT_ENTER_SETTINGS` via the
     `default:` case (controller_main.cpp:77-79). Add: also call
     `mode_enter_settings(&dev_mode, millis())` so the controller enters its
     own settings mode.
   - Add `cfgget`/`cfgset`/`cfgsave`/`cfgreset` command handling (from Step 1)
5. In `loop()`:
   - Add `mode_tick(&dev_mode, now)` check
   - If mode changed to settings: call `wifi_ap_start(ssid, cfg.espnow_channel)`
   - If mode changed to live: call `wifi_ap_stop()` + reinit ESP-NOW
   - In settings mode, skip `send_keepalive()` — ESP-NOW is down
6. Add `settings_window_sec` to `controller_config_t` in config.h

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
   - Test mode_init with window > 0 enters settings at boot (controller boot window)
   - Test mode_enter_settings switches to MODE_SETTINGS
   - Test mode_tick timeout triggers exit
   - Test mode_is_settings returns correct state

2. **Integration test** (hardware): Boot → enter settings → WiFi AP starts →
   connect phone → verify parasol UI → timeout → back to live mode

3. **Manual test**:
   - Serial `settings` on controller triggers leaves' settings mode via ESP-NOW
     (broadcast) and the controller's own settings mode
   - `settings <id>` targets a single leaf (requires node_id assigned)

## Backlog

- WiFi AP password configuration
- STA mode for shared network configuration
- Multiple controller support
- parasol image upload (OTA)
- Settings-mode trigger via MIDI (not just serial)
