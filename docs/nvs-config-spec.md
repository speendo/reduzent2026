# NVS Config Spec

Date: 2026-08-19
Status: draft

## Purpose

Persistent device configuration via NVS flash, with serial config commands on
the controller. Replaces hardcoded `#define`s with loadable settings. WiFi AP
and settings/live mode state machine are future slices.

## Scope

- Config struct per role (leaf, controller)
- NVS load/save (blob storage)
- Serial config commands on the controller (`cfgget`, `cfgset`, `cfgsave`, `cfgreset`)
- Leaf config: struct + NVS only (serial commands deferred to WiFi AP slice)

## Config settings

### Common settings

| Key | Type | Range | Default | Devices | Description |
|-----|------|-------|---------|---------|-------------|
| `espnow_channel` | uint8 | 1–14 | 13 | controller, leaf | WiFi channel for ESP-NOW. Must match across all devices. Currently hardcoded to 13 in both firmwares. |

### Leaf settings

| Key | Type | Range | Default | Devices | Description |
|-----|------|-------|---------|---------|-------------|
| `channel` | uint8 | 0–15 | 0 | leaf (piezo + solenoid) | MIDI channel this leaf listens to. Frames on other channels are ignored. Currently hardcoded to 0 (`MY_CHANNEL`). |
| `actuator` | uint8 | `piezo` / `solenoid` | `piezo` | leaf | Actuator type. Routes `EVENT_NOTE` in the receive path (`actuator_note_action` in `lib/reduzent/actuator.h`): piezo drives the voice table, solenoid strikes its assigned note. Stored as uint8 (0 = piezo, 1 = solenoid); serial and web interfaces use the names. |
| `gpio_piezo` | uint8 | 0–28 | 3 | leaf | GPIO pin for the piezo output. Only used when `actuator = piezo`. |
| `gpio_solenoid` | uint8 | 0–28 | 4 | leaf | GPIO pin for the solenoid output. Only used when `actuator = solenoid`. |
| `solenoid_note` | uint16 | 0–127 | 36 | leaf (solenoid only) | MIDI note number that triggers this solenoid's strike. Only this note activates the solenoid; other notes are ignored. |
| `solenoid_hold_ms` | uint16 | 10–500 | 40 | leaf (solenoid only) | Duration in ms the solenoid coil stays energized after a strike. Must exceed the solenoid's mechanical pull-in time. Longer values press the striker against the surface (muting ring). |
| `solenoid_duty_min` | uint8 | 0–255 | 40 | leaf (solenoid only) | PWM duty cycle (0–255) at minimum velocity (note-on velocity = 1). Controls minimum coil current / strike force. |
| `solenoid_duty_max` | uint8 | 0–255 | 220 | leaf (solenoid only) | PWM duty cycle at maximum velocity (note-on velocity = 127). Controls maximum coil current / strike force. Velocity scales linearly between min and max. |
| `piezo_pitch_bend_range` | uint8 | 1–24 | 2 | leaf (piezo only) | Full-scale pitch bend range in semitones. A 14-bit MIDI pitch bend of 0 = −range, 8192 = center, 16383 = +range. Currently hardcoded as `PITCH_BEND_RANGE`. |
| `piezo_adsr_attack_ms` | uint16 | 0–5000 | 5 | leaf (piezo only) | ADSR attack time in milliseconds. Time from note-on to peak amplitude. |
| `piezo_adsr_decay_ms` | uint16 | 0–5000 | 100 | leaf (piezo only) | ADSR decay time in milliseconds. Time from peak to sustain level. |
| `piezo_adsr_sustain_pct` | uint8 | 0–100 | 70 | leaf (piezo only) | ADSR sustain level as a percentage of peak amplitude (0 = silence, 100 = full). Held notes sustain at this level until note-off. |
| `piezo_adsr_release_ms` | uint16 | 0–5000 | 100 | leaf (piezo only) | ADSR release time in milliseconds. Time from note-off to silence. |
| `node_id` | uint8 | 0–254 | 255 | leaf | Unique identity for this leaf. Used to target a single leaf in settings mode (`settings <id>` only triggers that leaf) and to name the settings-mode AP (`reduzent-leaf-<node_id>`). 255 = unassigned (SSID falls back to a MAC-derived suffix). |
| `settings_window_sec` | uint16 | 0–300 | 30 | leaf | How long (in seconds) the leaf stays in settings mode after an `ENTER_SETTINGS` trigger before returning to live mode. 0 = return to live immediately. |

### Controller settings

| Key | Type | Range | Default | Devices | Description |
|-----|------|-------|---------|---------|-------------|
| `settings_window_sec` | uint16 | 0–300 | 30 | controller | How long (in seconds) the controller stays in settings mode after boot before switching to live mode. 0 = skip settings mode at boot (boot straight to live). |

## NVS storage

- Namespace: `"instrument"`
- Keys: `"leaf_cfg"` (blob, `leaf_config_t`), `"ctrl_cfg"` (blob, `controller_config_t`)
- `config_load(namespace, struct*)` reads NVS → struct; returns 0 on success, -1 if not found or CRC mismatch (caller fills defaults first, so -1 = "use defaults")
- `config_save(namespace, struct*)` writes struct → NVS with a simple CRC appended for corruption detection
- `config_defaults(struct*)` fills a struct with the compile-time defaults from the table above (implemented as a macro → `config_defaults_impl` dispatching on `sizeof`)

The CRC is a simple byte-sum of the struct contents, appended as a trailing uint8. On load, if the CRC doesn't match, the struct retains the defaults the caller passed in. This catches partial writes and flash wear without a full versioning scheme.

## Serial commands (controller only)

These are local serial commands processed by the controller firmware. They do
not produce ESP-NOW frames.

| Command | Effect |
|---------|--------|
| `cfgget` | Print all controller config fields as `key=value` lines to serial |
| `cfgset <key> <value>` | Set one field in RAM. Validates range. Prints error on invalid key or value. |
| `cfgsave` | Write the current RAM config to NVS. Prints confirmation. |
| `cfgreset` | Restore compile-time defaults to RAM (does not touch NVS). Print the defaults. |

Enum fields accept names on `cfgset` and print names on `cfgget`:

| Field | Stored as | Accepted names |
|-------|-----------|----------------|
| `actuator` | 0 / 1 | `piezo` / `solenoid` |

Leaf config commands (`cfgget leaf`, `cfgset leaf`, etc.) are deferred to the
WiFi AP / parasol slice, where the controller can forward config to leaves over
unicast ESP-NOW or a leaf can be configured directly via its own AP.

## Files

| File | What | Testable |
|------|------|----------|
| `lib/reduzent/config.h` | Structs, defaults, NVS load/save, CRC — header-only | structs + defaults + CRC: native. NVS read/write: manual only. |
| `lib/reduzent/config_parser.h` | Serial command parsing for `cfgget`/`cfgset`/`cfgsave`/`cfgreset` | native (pure string → config struct manipulation) |
| `src/leaf_main.cpp` | Load config at boot, replace `#define`s with struct fields | manual (hardware) |
| `src/controller_main.cpp` | Load config at boot, replace `#define ESP_NOW_CHANNEL`, wire serial commands | manual (hardware) |
| `test/test_config/test_config.cpp` | Native tests: defaults, CRC round-trip, range validation, parser | `pio test -e native` |
| `test/test_config_parser/test_config_parser.cpp` | Native tests: command parsing, get/set/reset | `pio test -e native` |

## Integration with leaf_main.cpp

```c
#include "config.h"

static leaf_config_t cfg;

void setup() {
    Serial.begin(115200);
    config_defaults(&cfg);
    config_load("leaf_cfg", &cfg);

    // Replace #defines with cfg fields:
    //   cfg.channel            was MY_CHANNEL
    //   cfg.gpio_piezo         was PIEZO_PIN
    //   cfg.gpio_solenoid      was SOLENOID_PIN
    //   cfg.solenoid_*         was SOLENOID_* defines
    //   cfg.piezo_pitch_bend_range was PITCH_BEND_RANGE
    //   cfg.piezo_adsr_*       was ENVELOPE_DEFAULT params
    //   cfg.espnow_channel     was ESP_NOW_CHANNEL
    ...
}
```

## Integration with controller_main.cpp

```c
#include "config.h"

static controller_config_t cfg;

void setup() {
    Serial.begin(115200);
    config_defaults(&cfg);
    config_load("ctrl_cfg", &cfg);

    // Replace #define:
    //   cfg.espnow_channel was ESP_NOW_CHANNEL
    esp_wifi_set_channel(cfg.espnow_channel, WIFI_SECOND_CHAN_NONE);
    ...
}
```

## Future settings

These settings are documented here for when they're needed, but are not
included in the config structs yet. Add them when the consuming code is written.

| Key | Type | Range | Default | Devices | Description |
|-----|------|-------|---------|---------|-------------|
| `piezo_arpeggio_rate_hz` | uint16 | 10–250 | 60 | leaf (piezo, render_path 0) | How many times per second the arpeggio index advances and LEDC frequency is retuned. Currently hardcoded as `ARP_TICK_MS = 16` ms (~62.5 Hz). Higher = faster chord cycling. |
| `piezo_vibrato_depth_max_cents` | uint8 | 0–100 | 50 | leaf (piezo only) | Maximum vibrato depth in cents, applied when CC1 = 127. The LFO runs at 6 Hz; CC1 (0–127) scales linearly from 0 to this value. Currently hardcoded to 50 in `vibrato_cents()`. |

## Backlog

- Leaf config forwarding from the controller over ESP-NOW (unicast, needs pairing)
- Settings-mode AP password (per device)
- STA mode for configuring multiple devices on a shared network
- Compile-time actuator split (separate piezo/solenoid envs) if footprint demands
- Solenoid velocity curve as a full editable table (MVP: min/max scalars)
- `node_id` consumed by unicast ESP-NOW targeting (requires auto-discovery / pairing; the field itself now exists)
- `piezo_arpeggio_rate_hz` wired into the arpeggio render loop
- `piezo_vibrato_depth_max_cents` wired into `vibrato_cents()`
