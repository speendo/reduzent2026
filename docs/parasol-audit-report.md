# parasol Audit Report

Date: 2026-08-20
parasol version tested: v0.6.3
Integration context: reduzent2026 (ESP32-C3, ESP-NOW MIDI actuator controller)

## Executive Summary

parasol delivers on its core promise: a compact, well-structured web
configuration UI for ESP32 with real-time WebSocket sync. The C API is
clean and the dirty-flag state machine is well-designed. However,
v0.6.3 has several integration barriers -- a missing asset generator,
forward-declaration bugs, a const-correctness issue, and an outdated
dependency declaration -- that require workarounds in PlatformIO
projects. Documentation is solid but has version references that lag
behind the release.

## What Works Well

**API design.** The group/field registration model is intuitive. The
`prsl_field_opts_t` struct cleanly separates callbacks (`on_get`/`on_set`),
documentation (`help`), and validation (`attrs`). Adding 12 fields across
3 groups took under an hour with no API surprises beyond the bugs noted
below.

**Dirty-flag state machine.** Developer-driven `prsl_set_dirty()` is
the right call -- automatic dirty tracking gets fragile fast. The
10-case state machine in WS_PROTOCOL.md handles echo resolution and
collision gracefully.

**Wire format.** Partial-apply (send only changed fields) minimizes
bandwidth. The `[type, label, {value, ...}]` tuple format is compact
and easy to parse on both sides.

**Status vs. settings split.** `prsl_broadcast_status()` sends only
read-only fields, keeping the hot-path (live telemetry) lightweight.
This matters on constrained MCUs.

**Live reload.** The WebSocket push model means firmware can update
status fields without polling. The browser re-renders automatically.

**Pico CSS.** The default UI is clean and functional with zero
configuration. Forms render correctly. The reset/reboot buttons work as
documented; **the Save button does not** — see Issues 10-12 below (persistence
requires firmware to drive `prsl_set_dirty()` and an `on_set` callback that
writes the store, neither of which the docs make obvious).

**Native test suite.** 132/132 tests pass in the native environment.
The FreeRTOS stub approach for host testing is well-executed and
gives confidence in the store logic without hardware.

## Issues Found

### Library Issues

**1. Missing generated assets (HIGH).**
The v0.6.3 tarball does NOT include `prsl_assets.h` / `prsl_assets.c`.
The CMake build system generates them from `index.html`, `app.min.js`,
and `pico.jade.min.css` during build. PlatformIO has no equivalent
CMake step, so projects must provide their own `extra_script.py` to
replicate this. This is the single largest integration barrier.

Workaround: `scripts/parasol_setup.py` (221 lines) handles asset
generation, struct patching, and const-correctness fixes. It runs as
a PlatformIO `pre:scripts/parasol_setup.py` extra script.

**2. prsl_store_t forward-declaration bug (HIGH).**
`prsl.h` declares `prsl_build_settings_payload(prsl_store_t *store)` but
`prsl_store_t` is only defined in `src/prsl_store.h`. In C, this is a
use of an incomplete type and fails to compile when `prsl_store_t` is
passed by value. In the current v0.6.3 tarball, the forward declaration
IS present (lines 6-7 of `prsl.h`), suggesting this was fixed between
the initial discovery and the release. However, the `prsl_store_t`
typedef in `prsl_store.h` uses an anonymous struct, which prevents
forward-declaration in C++. The struct must be named `prsl_store_s`.

Workaround: `parasol_setup.py` patches `prsl_store.h` to use
`struct prsl_store_s { ... }` and adds the forward declaration
to `prsl.h`.

**3. const-correctness mismatch (MEDIUM).**
`prsl_build_settings_payload(const prsl_store_t *store)` was declared
`const` in `prsl.h` but the definition in `prsl.cpp` called
`prsl_store_is_dirty(store)` which takes a non-const pointer. In
C++ this is a type error; in C it compiles but is semantically wrong.

Workaround: `parasol_setup.py` removes `const` from the declaration.
In v0.6.3, the declaration is already non-const in the shipped
`prsl.h`, but the API_REFERENCE.md examples still show the old
`const` signature.

**4. ESPAsyncWebServer dependency mismatch (MEDIUM).**
`library.json` declares `"me-no-dev/ESP Async WebServer": "~3.11"`.
This is the original, unmaintained library (last update Jan 2025).
The actively maintained fork is `esp32async/ESPAsyncWebServer@^3.12`.
PlatformIO may pull the wrong version or fail to resolve deps.

Workaround: Explicitly declare `esp32async/ESPAsyncWebServer@^3.12`
in `platformio.ini` lib_deps, which overrides the transitive dep.

**5. Duplicate AsyncTCP libraries (MEDIUM).**
PlatformIO's dependency resolution can pick up both `AsyncTCP`
(ESP32Async) and `Async TCP` (mathieucarbou) simultaneously, causing
linker conflicts. The correct approach is to NOT list AsyncTCP
explicitly and let ESPAsyncWebServer pull it transitively.

Workaround: Remove any explicit `AsyncTCP` from lib_deps. Add
`lib_ignore = AsyncTCP_RP2040W` to prevent the RP2040 port from
being pulled in.

**6. No prsl_stop() / deinit (LOW).**
The API reference states "no explicit deinit -- the web server
lives for the ESP32's full uptime." This is fine for single-purpose
config servers but problematic when settings mode is temporary
(e.g., enter for 30 seconds after boot, then shut down WiFi).

Workaround: Call `server.end()` + `WiFi.mode(WIFI_OFF)` directly.
This works but bypasses parasol's lifecycle management.

**7. C99 compound literals in API examples (LOW).**
API_REFERENCE.md examples use `&(prsl_field_opts_t){...}` which is
valid C99 but invalid in C++ (Arduino compiles as C++). Users must
declare `static const` variables instead. The library code itself does
not use compound literals, so this is a documentation issue only.

**8. Menu bar too wide on mobile (LOW).**
The top-bar navigation groups span the full horizontal width,
which causes text truncation / horizontal scroll on narrow phone
screens. A responsive layout or collapsible menu would help.

**9. Save button has no loading/success feedback (LOW).**
Clicking Save sends an HTTP POST to `/api/settings/save`. The button
visibly disappears only after the response returns and the WebSocket
push with `_dirty: false` arrives. There is no spinner, disabled state,
or success toast during the round-trip. On slow connections or when the
firmware is slow to return, the user has no indication anything is
happening. A brief `aria-busy="true"` + a success checkmark would fix
this.

**10. on_set callback must write the store itself; the shipped example doesn't (HIGH).**
In `prsl_apply_body()` (`src/prsl_body.c`), when a field registers `on_set`,
the library does **not** update the store — the callback is fully responsible
for validating *and* persisting the value (via `prsl_set_str`). The
`else if (f)` branch (store write) is skipped whenever `on_set` exists.
`API_REFERENCE.md` describes `on_set` as merely "React to value changes …
return ESP_OK to accept", and `examples/basic/main.c` (`on_ssid_change`)
only prints + validates without calling `prsl_set_str`. Following the
documented example, applied values are silently dropped and the save
callback persists the stale value. Either the docs must state that `on_set`
must call `prsl_set_str`, or the library should store the value itself.

**11. prsl_get() only returns string values; typed setters are unreadable (MEDIUM).**
`prsl_get()` (`src/prsl.cpp`) returns NULL unless the stored cJSON node is a
string (`cJSON_IsString`). `prsl_set_int()` / `prsl_set_float()` /
`prsl_set_bool()` store JSON numbers/booleans, so a firmware that loads values
with typed setters (a common pattern for a load callback) and reads them back
with `prsl_get()` in the save callback silently gets NULL and can persist
defaults. `API_REFERENCE.md`'s PRSL_NUMBER row ("Value is string, server
serializes as JSON number") hints at this but the string-only `prsl_get`
contract is not stated explicitly. Recommend `prsl_set_str` for any value the
firmware needs to read back, and a docs note that `prsl_get` is string-only.

**12. The library never sets _dirty; Save can be a silent no-op (MEDIUM).**
`_dirty` is only ever *cleared* by the library (on save success) — never set.
The browser applies changes over the WebSocket immediately, the server echoes
`_dirty: false`, and the client re-syncs its per-field baseline. The client's
Save click posts `/api/settings/save` only while `_dirty` is true (or a field
is un-echoed, which resolves in milliseconds). So if the firmware never calls
`prsl_set_dirty(true)`, the Save button click sends **no POST at all** and
nothing persists — with no error shown. The "developer-driven" contract is
documented, but the sharp consequence (a dead, feedback-free Save button) is
not called out.

**13. Underscore-prefixed groups are silently dropped end-to-end (MEDIUM).**
The browser JS filters out any group whose id starts with `_`
(`if("_"!==i[0])` in `O()`/`S()`/`W()` of `app.min.js`), and
`prsl_apply_body` skips `group->string[0]=='_'`. So a `_system` group (as we
initially used for the internal "leave settings" switch) is never rendered,
never applied, and never read back. The spec labels underscore keys "meta
fields, never components", but this is easy to miss — a firmware author picks
`_system` for internal fields and gets an invisible section with no warning.
Worth an explicit warning + troubleshooting entry.

**14. Save body handler is broken for real saves (HIGH — confirmed on hardware).**
The `/api/settings/save` handler (`prsl.cpp`) has two bugs that together made
every real save fail with `400`:
- `cJSON_ParseWithLength((const char *)data, total)` parses `total` bytes from
  the chunk pointer. ESPAsyncWebServer's `handleBody` passes one buffer per
  TCP read (verified in `WebRequest.cpp`/`WebHandlers.cpp`) and does not
  accumulate, so any body arriving in more than one read over-reads the chunk
  and fails with `Invalid JSON`.
- `cJSON_GetObjectItem(msg, "data")` expects a top-level `"data"` wrapper, but
  the browser posts the settings object directly (and `WS_PROTOCOL.md`/the
  architecture spec document the body without a wrapper), so a successfully
  parsed body fails with `Missing data`.

Workaround: `parasol_setup.py` now patches `prsl.cpp` to accumulate the body
in `request->_tempObject`, act on the final chunk (`index + len == total`),
and apply the parsed object itself as the body.

**15. Reset button is always visible (LOW — by design, awkward).**
The client's `x()` shows Reset whenever an `on_reset` callback exists
(`a.hidden = !(c || h)`, `h = _show_reset`), independent of dirty state. On a
clean form there is nothing to reset, so the button looks like a bug. Also,
the `/api/settings/reset` endpoint calls `on_reset` but never clears `_dirty`,
so even after resetting, the button (and Save) stay visible. Workarounds in
reduzent: `parasol_setup.py` patches `app.min.js` (`a.hidden=!c` → show Reset
only while dirty), and the load/reset callback calls `prsl_set_dirty(false)`.

### Documentation Issues

**1. Stale version references.**
README.md installation instructions reference `v0.6.0` in the tarball
URL and git tag. The actual latest release is v0.6.3. This will cause
users to install an outdated version. The docs table also references
files that exist at v0.6.3 but the links use unversioned paths.

**2. API_REFERENCE.md const signature drift.**
The API reference shows `prsl_build_settings_payload(const prsl_store_t *)`
but the actual code in v0.6.3 uses a non-const signature. The API
reference should match the implementation.

**3. Missing PlatformIO instructions.**
README.md only mentions the tarball and git URL. There are no
PlatformIO-specific notes (extra_scripts, lib_ignore, dependency
overrides). Given that PlatformIO is the primary build system for
ESP32 Arduino projects, this is a significant gap.

**4. No troubleshooting section.**
Common issues (asset generation, dependency conflicts, C++ compound
literals) are not documented anywhere. Users will hit these same
walls. Missing also: the Issues 10-13 traps (on_set must write the store,
prsl_get is string-only, dirty must be set by firmware, no `_`-prefixed
groups).

**5. CHANGELOG.md stops at 0.6.0.**
The changelog has entries for 0.1.0 through 0.6.0 but no entry for
0.6.3. Changes between 0.6.0 and 0.6.3 are undocumented.

**6. Architecture spec referenced but separate.**
`docs/superpowers/specs/2026-06-18-unified-settings-design.md` is
referenced in the docs table but lives in a `superpowers` directory.
This is an internal development artifact, not user-facing
documentation. Users following the link may be confused by the
superpowers workflow context.

## Recommendations

**Priority 1 -- Fix integration blockers:**

1. **Include generated assets in tarball.** The CMake build should
   produce `prsl_assets.h` / `prsl_assets.c` and include them in
   the release tarball. This eliminates the need for per-platform
   asset generation scripts.

2. **Fix dependency declaration.** Update `library.json` to reference
   `esp32async/ESPAsyncWebServer` (the maintained fork) instead of
   `me-no-dev/ESP Async WebServer`. Add `lib_ignore` guidance.

3. **Fix const-correctness.** Ensure `prsl_build_settings_payload`
   declaration and definition agree on const-ness. The non-const
   version is correct since the store is locked via mutex.

**Priority 2 -- Documentation:**

4. **Update README.md** with v0.6.3 URLs, PlatformIO-specific setup
   instructions, and a troubleshooting section.

5. **Update CHANGELOG.md** with 0.6.1-0.6.3 changes.

6. **Align API_REFERENCE.md** with actual code signatures.

**Priority 3 -- Nice-to-have:**

7. **Add prsl_stop()** for use cases where settings mode is temporary.

8. **Consider a PlatformIO-specific library.json** or documented
   extra_scripts pattern.

## Integration Notes

**What we learned integrating parasol into reduzent2026:**

- The `extra_script.py` approach works but is fragile. It patches
  library source files at build time, which means changes to parasol
  upstream may break the patches. Pin to v0.6.3 explicitly.

- The `server.end()` + `WiFi.mode(WIFI_OFF)` pattern for exiting
  settings mode works in practice but is not part of parasol's API.
  Monitor for future `prsl_stop()` additions.

- Field registration order matters: all groups must be added before
  their fields, and all registration must happen before `prsl_init`.
  This is documented but easy to miss in practice.

- The `parasol_config.json` file (`lib/reduzent/parasol_config.json`)
  controls page title, logo, and favicon. `always_show_save: true` keeps the
  Save button permanently visible (useful for settings-only modes); reduzent
  uses `false` so the button appears on change and hides after a successful
  save. **Config changes require regenerating the baked-in assets** — the
  PlatformIO extra_script only regenerates when the assets are missing or the
  config file is newer (see `scripts/parasol_setup.py`).

- The WebSocket protocol is clean and well-documented. The partial-apply
  pattern is efficient for constrained devices.

- Build footprint is excellent: ~12% RAM, ~58-69% flash. The gzip
  compression of static assets keeps flash usage reasonable.

- The dirty-flag model requires firmware to explicitly call
  `prsl_set_dirty(true)` when external state changes. This is
  correct for our use case (MIDI-triggered config changes) but
  requires discipline.

**Save-flow debugging findings (2026-08-20, see Issues 10-13):** our first
integration followed the documented example (fields with `on_set` = NULL,
values loaded via `prsl_set_int`, no `prsl_set_dirty`), and the result was
that the Save button appeared but clicking it persisted nothing — no POST ever
reached the firmware (client-side `_dirty` never true, baseline re-synced via
the WS echo), and even if it had, `prsl_get` would have read NULL for the
int-loaded fields and the save would have clobbered unchanged settings to
defaults. Working integration requires, per field: an `on_set` that validates,
writes the value via `prsl_set_str`, and calls `prsl_set_dirty(true)`; load
values as strings; and keep group ids free of a leading underscore.
