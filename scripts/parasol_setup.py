"""
PlatformIO extra_script: generate parasol assets and apply patches.

Runs before the build to:
1. Generate prsl_assets.h / prsl_assets.c from parasol source + config
2. Patch prsl_store.h to use a named struct (for forward-decl compatibility)
3. Patch prsl.h to add prsl_store_t forward declaration
4. Patch prsl.h and prsl.cpp to fix const-correctness
"""

import os
Import("env")  # noqa: F821 – PlatformIO SCons global


def find_parasol_dirs():
    """Find all parasol library directories in libdeps."""
    dirs = []
    for base in [".pio/libdeps/leaf", ".pio/libdeps/controller"]:
        p = os.path.join(base, "parasol")
        if os.path.isdir(p):
            dirs.append(p)
    return dirs


def assets_stale(parasol_dir, config_path):
    """True when generated assets are missing or older than any source asset.

    Assets bake in the parasol_config.json values (title, logo, favicon,
    always_show_save) and the source index.html / app.min.js / pico CSS, so
    changing any of them must regenerate the assets.
    """
    src_dir = os.path.join(parasol_dir, "src")
    assets_h = os.path.join(src_dir, "prsl_assets.h")
    assets_c = os.path.join(src_dir, "prsl_assets.c")
    if not (os.path.exists(assets_h) and os.path.exists(assets_c)):
        return True
    sources = [
        config_path,
        os.path.join(parasol_dir, "index.html"),
        os.path.join(parasol_dir, "app.min.js"),
        os.path.join(parasol_dir, "pico.jade.min.css"),
    ]
    try:
        assets_mtime = max(os.path.getmtime(assets_h), os.path.getmtime(assets_c))
        return any(os.path.getmtime(s) > assets_mtime for s in sources)
    except OSError:
        return True


def generate_assets(parasol_dir):
    """Generate prsl_assets.h and prsl_assets.c by invoking the existing CMake script."""
    src_dir = os.path.join(parasol_dir, "src")
    assets_h = os.path.join(src_dir, "prsl_assets.h")
    assets_c = os.path.join(src_dir, "prsl_assets.c")

    config_path = "lib/reduzent/parasol_config.json"
    if not assets_stale(parasol_dir, config_path):
        return

    import subprocess
    cmake_script = os.path.join(parasol_dir, "cmake", "generate_assets.cmake")
    out_dir = os.path.join(parasol_dir, "generated")
    os.makedirs(out_dir, exist_ok=True)

    cmd = [
        "cmake",
        f"-DASSETS_SRC={parasol_dir}",
        f"-DCONFIG_FILE={config_path}",
        f"-DOUT_DIR={out_dir}",
        "-P", cmake_script,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[parasol] CMake asset generation failed:\n{result.stderr}")
        return

    # Move generated files to src/ where parasol expects them
    import shutil
    for name in ["prsl_assets.h", "prsl_assets.c"]:
        src = os.path.join(out_dir, name)
        dst = os.path.join(src_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, dst)

    print(f"[parasol] Generated prsl_assets.h and prsl_assets.c via CMake in {src_dir}")


def patch_prsl_store_h(parasol_dir):
    """Patch prsl_store.h: anonymous struct → named struct prsl_store_s.

    The original typedef for prsl_store_t is:
        typedef struct {
            prsl_field_t *fields;
            ...
            SemaphoreHandle_t mutex;
        } prsl_store_t;

    We need to replace ONLY the store struct (which contains SemaphoreHandle_t
    and prsl_field_t fields), NOT the prsl_field_t or prsl_group_meta_t structs.
    """
    path = os.path.join(parasol_dir, "src", "prsl_store.h")
    with open(path, "r") as f:
        content = f.read()

    original = content

    # Only patch if the store struct is still anonymous (doesn't already use prsl_store_s)
    if "struct prsl_store_s" not in content:
        # Replace the specific anonymous store struct pattern
        old = "typedef struct {\n" \
              "    prsl_field_t *fields;\n" \
              "    int count;\n" \
              "    int capacity;\n" \
              "    bool dirty;\n" \
              "    prsl_group_meta_t *groups;\n" \
              "    int group_count;\n" \
              "    int group_capacity;\n" \
              "    SemaphoreHandle_t mutex;\n" \
              "} prsl_store_t;"
        new = "typedef struct prsl_store_s {\n" \
              "    prsl_field_t *fields;\n" \
              "    int count;\n" \
              "    int capacity;\n" \
              "    bool dirty;\n" \
              "    prsl_group_meta_t *groups;\n" \
              "    int group_count;\n" \
              "    int group_capacity;\n" \
              "    SemaphoreHandle_t mutex;\n" \
              "} prsl_store_t;"
        content = content.replace(old, new)

    if content != original:
        with open(path, "w") as f:
            f.write(content)
        print(f"[parasol] Patched {path}")
    else:
        print(f"[parasol] prsl_store.h already uses named struct — no patch needed")


def patch_prsl_h(parasol_dir):
    """Patch prsl.h: add forward declaration + remove const from payload builder."""
    path = os.path.join(parasol_dir, "include", "prsl.h")
    with open(path, "r") as f:
        content = f.read()

    original = content

    # Add forward declaration of prsl_store_t if missing
    if "struct prsl_store_s;" not in content:
        content = content.replace(
            '#include "cJSON.h"\n\n#ifdef __cplusplus',
            '#include "cJSON.h"\n\nstruct prsl_store_s;\ntypedef struct prsl_store_s prsl_store_t;\n\n#ifdef __cplusplus',
        )

    # Remove const from prsl_build_settings_payload parameter
    content = content.replace(
        "cJSON *prsl_build_settings_payload(const prsl_store_t *store);",
        "cJSON *prsl_build_settings_payload(prsl_store_t *store);",
    )

    if content != original:
        with open(path, "w") as f:
            f.write(content)
        print(f"[parasol] Patched {path}")
    else:
        print(f"[parasol] prsl.h already patched")


def patch_prsl_cpp(parasol_dir):
    """Remove const from prsl_build_settings_payload definition."""
    path = os.path.join(parasol_dir, "src", "prsl.cpp")
    with open(path, "r") as f:
        content = f.read()

    original = content
    content = content.replace(
        "cJSON *prsl_build_settings_payload(const prsl_store_t *store) {",
        "cJSON *prsl_build_settings_payload(prsl_store_t *store) {",
    )

    if content != original:
        with open(path, "w") as f:
            f.write(content)
        print(f"[parasol] Patched {path}")
    else:
        print(f"[parasol] prsl.cpp already patched")


def patch_prsl_cpp_save_handler(parasol_dir):
    """Fix the /api/settings/save body handler in prsl.cpp.

    Upstream v0.6.3 has two bugs here:
      1. cJSON_ParseWithLength((const char *)data, total) — ESPAsyncWebServer
         delivers the body in chunks without accumulating (handleBody passes
         one buffer per chunk), so multi-chunk bodies over-read and fail with
         "Invalid JSON".
      2. cJSON_GetObjectItem(msg, "data") — the browser posts the settings
         object directly (no "data" wrapper), so single-chunk bodies fail with
         "Missing data".

    Replacement accumulates the body in request->_tempObject, acts on the
    final chunk only, and applies the parsed object itself as the body.
    """
    path = os.path.join(parasol_dir, "src", "prsl.cpp")
    with open(path, "r") as f:
        content = f.read()

    original = content

    content = content.replace(
        "#include <string.h>\n#include <stdio.h>",
        "#include <string.h>\n#include <stdio.h>\n#include <stdlib.h>",
    )

    old = '''            cJSON *msg = cJSON_ParseWithLength((const char *)data, total);
            if (!msg) {
                req->send(400, "text/plain", "Invalid JSON");
                return;
            }
            cJSON *body = cJSON_GetObjectItem(msg, "data");
            if (!body) {
                cJSON_Delete(msg);
                req->send(400, "text/plain", "Missing data");
                return;
            }'''
    new = '''            /* ESPAsyncWebServer delivers the body in chunks and does not
               accumulate; handleBody passes one buffer per chunk. Build the
               full body in _tempObject and act on the final chunk only. */
            if (index == 0) {
                free(req->_tempObject);
                req->_tempObject = NULL;
            }
            if (total > 0 && len > 0) {
                uint8_t *buf = (uint8_t *)realloc(req->_tempObject, index + len + 1);
                if (!buf) {
                    free(req->_tempObject);
                    req->_tempObject = NULL;
                    req->send(500, "text/plain", "Out of memory");
                    return;
                }
                memcpy(buf + index, data, len);
                buf[index + len] = '\\0';
                req->_tempObject = buf;
            }
            if (index + len != total) return;  /* more chunks pending */

            cJSON *msg = NULL;
            if (total > 0) {
                msg = cJSON_ParseWithLength((const char *)req->_tempObject, total);
                free(req->_tempObject);
                req->_tempObject = NULL;
            }
            if (!msg) {
                req->send(400, "text/plain", "Invalid JSON");
                return;
            }
            /* The browser posts the settings object directly (no "data" wrapper). */
            cJSON *body = msg;'''
    content = content.replace(old, new)

    if content != original:
        with open(path, "w") as f:
            f.write(content)
        print(f"[parasol] Patched {path} (save body handler: accumulate + no data wrapper)")
    else:
        print(f"[parasol] prsl.cpp save body handler already patched")


def patch_app_js(parasol_dir):
    """Show the Reset button only while dirty (client x(): a.hidden = !(c || h)).

    Upstream v0.6.3 shows Reset whenever an on_reset callback exists, even on a
    clean form. We want it to appear only when there are unsaved changes.
    """
    path = os.path.join(parasol_dir, "app.min.js")
    with open(path, "r") as f:
        content = f.read()

    original = content
    content = content.replace("a.hidden=!(c||h)", "a.hidden=!c")

    if content != original:
        with open(path, "w") as f:
            f.write(content)
        print(f"[parasol] Patched {path} (Reset button shows only when dirty)")
    else:
        print(f"[parasol] app.min.js already patched (or pattern not found)")


# ── Main ─────────────────────────────────────────────────────────
parasol_dirs = find_parasol_dirs()
if parasol_dirs:
    for parasol_dir in parasol_dirs:
        print(f"[parasol] Processing {parasol_dir}")
        # Patch app.min.js BEFORE generating assets: assets embed the JS.
        patch_app_js(parasol_dir)
        patch_prsl_cpp_save_handler(parasol_dir)
        generate_assets(parasol_dir)
        patch_prsl_store_h(parasol_dir)
        patch_prsl_h(parasol_dir)
        patch_prsl_cpp(parasol_dir)
else:
    print("[parasol] parasol library not found in libdeps (first build?)")
