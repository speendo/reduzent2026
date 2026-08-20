# parasol Integration + Web UI Design

Date: 2026-08-19
Status: draft

## Purpose

Integrate the parasol library to provide a web-based configuration UI for
both leaves and the controller. This is Steps 4-5 of the parasol integration
roadmap (Steps 1-3: NVS config + settings mode + WiFi AP).

## Scope

- Add parasol library via lib_deps
- Register settings groups and fields per NVS config spec
- Wire save/reset callbacks to NVS
- Configure parasol build settings
- Test web UI functionality

## Dependencies

- Step 1: NVS config foundation (config.h, config_parser.h)
- Step 2-3: Settings mode + WiFi AP (mode.h, wifi_ap.h)
- parasol library v0.6.3

## Design

### parasol Library Integration

**File:** `platformio.ini`

Add to both leaf and controller environments:
```ini
lib_deps =
    https://github.com/speendo/parasol/releases/download/v0.6.3/parasol-v0.6.3.tar.gz
    ESP Async WebServer
    AsyncTCP
```

**Note:** the parasol README pins v0.6.0, but that release does not exist
(actual releases: v0.6.3 / v0.5.1 / v0.5.0). Verify the exact asset filename at
install time.

**Spike before Step 4:** build parasol + ESPAsyncWebServer for the C3 env as a
throwaway proof before wiring any firmware. The C3 has ~320 KB usable SRAM and
AP + ESPAsyncWebServer + parasol assets is tight; confirm it links and runs
before committing to the integration.

### Field Registration Strategy

**Approach:** Register fields in a shared module that both firmwares can use,
with firmware-specific fields added separately.

**File:** `lib/reduzent/parasol_setup.h` (new)

```c
// Common fields (both leaf and controller)
void parasol_register_common_fields(void);

// Leaf-specific fields
void parasol_register_leaf_fields(void);

// Controller-specific fields
void parasol_register_controller_fields(void);
```

### Leaf Settings Groups

Based on `docs/nvs-config-spec.md`:

#### Group: "network" (WiFi / ESP-NOW)
| Field | Type | Key | Range | Default |
|-------|------|-----|-------|---------|
| ESP-NOW Channel | NUMBER | espnow_channel | 1-14 | 13 |
| Settings Window (s) | NUMBER | settings_window_sec | 0-300 | 30 |

#### Group: "leaf" (Leaf Identity)
| Field | Type | Key | Range | Default |
|-------|------|-----|-------|---------|
| Node ID | NUMBER | node_id | 0-254 | 255 |
| MIDI Channel | NUMBER | channel | 0-15 | 0 |
| Actuator Type | SELECT | actuator | piezo/solenoid | piezo |

#### Group: "gpio" (Pin Configuration)
| Field | Type | Key | Range | Default |
|-------|------|-----|-------|---------|
| Piezo Pin | NUMBER | gpio_piezo | 0-28 | 3 |
| Solenoid Pin | NUMBER | gpio_solenoid | 0-28 | 4 |

#### Group: "solenoid" (Solenoid Settings)
| Field | Type | Key | Range | Default |
|-------|------|-----|-------|---------|
| Note Number | NUMBER | solenoid_note | 0-127 | 36 |
| Hold Duration (ms) | NUMBER | solenoid_hold_ms | 10-500 | 40 |
| Min Duty | NUMBER | solenoid_duty_min | 0-255 | 40 |
| Max Duty | NUMBER | solenoid_duty_max | 0-255 | 220 |

#### Group: "piezo" (Piezo Settings)
| Field | Type | Key | Range | Default |
|-------|------|-----|-------|---------|
| Pitch Bend Range | NUMBER | piezo_pitch_bend_range | 1-24 | 2 |
| Attack (ms) | NUMBER | piezo_adsr_attack_ms | 0-5000 | 5 |
| Decay (ms) | NUMBER | piezo_adsr_decay_ms | 0-5000 | 100 |
| Sustain (%) | NUMBER | piezo_adsr_sustain_pct | 0-100 | 70 |
| Release (ms) | NUMBER | piezo_adsr_release_ms | 0-5000 | 100 |

#### Group: "_system" (Internal, not persisted)
| Field | Type | Key | Notes |
|-------|------|-----|-------|
| Leave Settings Mode | SWITCH | _leave_settings | Underscore prefix = not saved to NVS. When toggled on and Save is clicked, the save callback triggers `mode_request_exit()` and the device returns to live mode immediately. |

### Controller Settings Groups

#### Group: "network" (WiFi / ESP-NOW)
| Field | Type | Key | Range | Default |
|-------|------|-----|-------|---------|
| ESP-NOW Channel | NUMBER | espnow_channel | 1-14 | 13 |
| Settings Window (s) | NUMBER | settings_window_sec | 0-300 | 30 |

#### Group: "_system" (Internal, not persisted)
| Field | Type | Key | Notes |
|-------|------|-----|-------|
| Leave Settings Mode | SWITCH | _leave_settings | Same behavior as leaf — triggers `mode_request_exit()` on save. |

### Save Callback

**File:** `lib/reduzent/parasol_setup.h`

```c
esp_err_t parasol_save_to_nvs(void);
```

**Implementation:**
1. Read all field values via `prsl_get()`
2. Check `_system._leave_settings` — if "1", set `leave_settings_request = true`
   (the device will exit settings on the next `mode_tick()` call)
3. Update the config struct (leaf_config_t or controller_config_t)
4. Call `config_save()` to persist to NVS (the `_leave_settings` switch is
   underscore-prefixed and therefore skipped by the save logic)
5. Return ESP_OK on success

**Validation:** reuse the range-check/parse helpers from Step 1
(`config_parser.h`), so parasol and serial `cfgset` accept exactly the same
values. `prsl_get()` returns strings; convert and validate through the shared
helpers before writing the struct. (Number fields also carry `min`/`max`
`attrs` for browser-side validation, but the firmware is the authority.)

> **Gap for the Step 4 plan:** Step 1's `config_parser.h` validates only the
> two controller fields (`espnow_channel`, `settings_window_sec`). parasol must
> validate all leaf fields too (node_id, channel, actuator, gpio, solenoid,
> piezo ADSR, ...). The Step 4 plan must extend the shared validation to both
> structs (or split it into a generic key→field validator that both
> `config_parser.h` and the parasol callbacks use) before wiring the save
> callback. Not blocking Steps 1-3.

### Reset Callback

```c
esp_err_t parasol_load_from_nvs(void);
```

**Implementation:**
1. Call `config_load()` to read from NVS
2. Update all field values via `prsl_set_*()` functions
3. Return ESP_OK on success

### parasol Configuration

**Build-time config** (lives inside the parasol library as
`parasol_config.json`; not uploaded as a runtime file):

```json
{
    "title": "reduzent",
    "logo": "/logo.png",
    "favicon": "/favicon.ico",
    "always_show_save": true
}
```

### Integration with Settings Mode

**Init once, start/stop on transition.** parasol requires all groups/fields to
be registered BEFORE `prsl_init()` (API_REFERENCE), and `AsyncWebServer` cannot
be rebuilt per entry. So registration + `prsl_init` happen exactly once; only
the server starts/stops on mode transitions (settings mode can be entered
multiple times: boot window, then again via signal).

**In leaf_main.cpp / controller_main.cpp:**

```c
// One-time, at first settings entry (or in setup()):
static bool parasol_ready = false;
if (!parasol_ready) {
    parasol_register_fields();  // register all groups/fields once
    prsl_init(&server, parasol_save_to_nvs, parasol_load_from_nvs, NULL);
    parasol_ready = true;
}

// On mode_enter_settings():
wifi_ap_start(ssid, cfg.espnow_channel);
prsl_start();   // (re)start serving

// On mode_exit_settings():
prsl_stop();    // server.end() — see teardown decision below
wifi_ap_stop();
// Reinit ESP-NOW
```

**Teardown on exit:** unverified whether returning AP→STA with `AsyncWebServer`
running is safe, and the server + parasol hold RAM on a battery leaf. Options:
- A (simpler): leave the server running; accept the RAM cost during live mode.
- B: `server.end()` on exit to live; re-create on next settings entry.
Decide after the Step 4 spike confirms behavior on hardware. If parasol exposes
no `prsl_stop`, the stop/restart is handled at the AsyncWebServer level.

### Static Assets

**Decision: PROGMEM (embedded in the firmware binary) for MVP.** Assets are
compiled in — no filesystem, no `data/` upload. `parasol_config.json` is a
*build-time* file inside the parasol library, not something shipped in a
`data/` directory here. LittleFS becomes an option only if OTA asset updates
are wanted (backlog).

### Files

| File | Action | Purpose |
|------|--------|---------|
| `lib/reduzent/parasol_setup.h` | Create | Field registration + callbacks |
| `platformio.ini` | Modify | Add parasol + dependencies |
| `src/leaf_main.cpp` | Modify | Integrate parasol with settings mode |
| `src/controller_main.cpp` | Modify | Integrate parasol with settings mode |

### Testing

1. **Spike (throwaway)**: build parasol + ESPAsyncWebServer on the C3 env; confirm
   it links and the AP serves the UI. Decide teardown option A vs B (see
   Integration with Settings Mode) from what this proves.
2. **Unit test** (native): Test field registration logic
3. **Integration test** (hardware):
   - Boot → enter settings → WiFi AP starts
   - Connect phone to AP → open browser → verify parasol UI loads
   - Change settings → save → verify NVS persistence
   - Reboot → verify settings loaded from NVS
   - Enter settings twice (boot window, then signal) → no double-registration crash
4. **Manual test**: Verify all fields render correctly and save/reset work

## Backlog

- LittleFS-based asset storage for OTA updates
- Custom branding (logo, favicon)
- Advanced field validation
- Multi-language support
- Field dependencies (show/hide based on other field values)
