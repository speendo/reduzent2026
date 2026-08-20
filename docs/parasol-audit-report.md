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
configuration. Forms render correctly and the save/reset/reboot
buttons work as documented.

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
walls.

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
  controls page title, logo, and favicon. The `always_show_save: true`
  setting is useful for settings-only modes.

- The WebSocket protocol is clean and well-documented. The partial-apply
  pattern is efficient for constrained devices.

- Build footprint is excellent: ~12% RAM, ~58-69% flash. The gzip
  compression of static assets keeps flash usage reasonable.

- The dirty-flag model requires firmware to explicitly call
  `prsl_set_dirty(true)` when external state changes. This is
  correct for our use case (MIDI-triggered config changes) but
  requires discipline.
