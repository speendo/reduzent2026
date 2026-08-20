"""
PlatformIO extra_script: generate parasol assets and apply patches.

Runs before the build to:
1. Generate prsl_assets.h / prsl_assets.c from parasol source + config
2. Patch prsl_store.h to use a named struct (for forward-decl compatibility)
3. Patch prsl.h to add prsl_store_t forward declaration
4. Patch prsl.h and prsl.cpp to fix const-correctness
"""

import gzip
import json
import os
Import("env")  # noqa: F821 – PlatformIO SCons global


def find_parasol_dirs():
    """Return only the current environment's parasol library directory.

    Each env gets its own copy under .pio/libdeps/<env>/parasol. Processing
    every env's copy from every pre-script caused concurrent asset generation
    to the same files (cmake -P writing prsl_assets.c in parallel), which
    interleaved writes and produced corrupt byte arrays. Scope to the env
    actually being built so each copy is written exactly once, by one process.
    """
    env_name = env.subst("$PIOENV")
    p = os.path.join(".pio", "libdeps", env_name, "parasol")
    return [p] if os.path.isdir(p) else []


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
    """Generate prsl_assets.h and prsl_assets.c from parasol source assets.

    Pure Python: read the source index.html / app.min.js / pico CSS, inject
    the parasol_config.json values, gzip, and emit C byte arrays. This does
    not depend on parasol's generate_assets.cmake, whose released v0.6.3
    version is broken (a foreach() with ';'-joined values splits JS content on
    semicolons, so fresh downloads fail with "File name too long").
    """
    src_dir = os.path.join(parasol_dir, "src")
    assets_h = os.path.join(src_dir, "prsl_assets.h")
    assets_c = os.path.join(src_dir, "prsl_assets.c")

    config_path = "lib/reduzent/parasol_config.json"
    if not assets_stale(parasol_dir, config_path):
        return

    # Read config
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = json.load(f)

    title = config.get("title", "PARASOL")
    logo = config.get("logo", "/logo.png")
    favicon = config.get("favicon", "/favicon.ico")
    always_show_save = "1" if config.get("always_show_save", False) else "0"

    with open(os.path.join(parasol_dir, "index.html"), "r") as f:
        html = f.read()
    html = html.replace("{{TITLE}}", title)
    html = html.replace("{{LOGO}}", logo)
    html = html.replace("{{FAVICON}}", favicon)
    html = html.replace("{{ALWAYS_SHOW_SAVE}}", always_show_save)

    with open(os.path.join(parasol_dir, "app.min.js"), "r") as f:
        js = f.read()
    with open(os.path.join(parasol_dir, "pico.jade.min.css"), "r") as f:
        css = f.read()

    html_gz = gzip.compress(html.encode("utf-8"), compresslevel=9)
    js_gz = gzip.compress(js.encode("utf-8"), compresslevel=9)
    css_gz = gzip.compress(css.encode("utf-8"), compresslevel=9)

    os.makedirs(src_dir, exist_ok=True)

    def hex_dump(data):
        parts = []
        for i, b in enumerate(data):
            parts.append(f"0x{b:02x}")
            if i < len(data) - 1:
                parts.append(",")
            if (i + 1) % 12 == 0 and i < len(data) - 1:
                parts.append("\n    ")
        return "".join(parts)

    def write_byte_array(f, var_name, data):
        f.write(f"const uint8_t {var_name}[] = {{\n    {hex_dump(data)}\n}};\n")
        f.write(f"const size_t {var_name}_len = {len(data)};\n\n")

    with open(assets_h, "w") as f:
        f.write("""#pragma once
#include <stddef.h>
#include <stdint.h>

typedef struct {
    const char *path;
    const char *mime;
    const uint8_t *data;
    size_t len;
} prsl_asset_t;

extern const prsl_asset_t prsl_assets[];
extern const size_t prsl_assets_count;
""")

    with open(assets_c, "w") as f:
        f.write('#include "prsl_assets.h"\n\n')
        write_byte_array(f, "index_html_gz", html_gz)
        write_byte_array(f, "app_min_js_gz", js_gz)
        write_byte_array(f, "pico_jade_min_css_gz", css_gz)
        f.write("const prsl_asset_t prsl_assets[] = {\n")
        f.write('    {"/", "text/html", index_html_gz, index_html_gz_len},\n')
        f.write('    {"/app.min.js", "application/javascript", app_min_js_gz, app_min_js_gz_len},\n')
        f.write('    {"/pico.jade.min.css", "text/css", pico_jade_min_css_gz, pico_jade_min_css_gz_len},\n')
        f.write("};\n")
        f.write("const size_t prsl_assets_count = 3;\n")

    print(f"[parasol] Generated prsl_assets.h and prsl_assets.c in {src_dir}")


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
