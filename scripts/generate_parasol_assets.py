#!/usr/bin/env python3
"""Generate prsl_assets.h and prsl_assets.c from parasol source assets.

Replaces the CMake generate_assets.cmake for PlatformIO builds.
Reads parasol_config.json for title/logo/favicon/always_show_save,
injects placeholders into index.html, gzips everything, and emits
C byte arrays.

Usage:
    python3 generate_parasol_assets.py <parasol_src_dir> <config_json> <out_dir>

Example:
    python3 generate_parasol_assets.py .pio/libdeps/leaf/parasol \
        lib/reduzent/parasol_config.json .pio/libdeps/leaf/parasol/src
"""

import gzip
import json
import os
import sys


def hex_dump(data: bytes) -> str:
    """Convert bytes to a C hex literal string."""
    parts = []
    for i, b in enumerate(data):
        parts.append(f"0x{b:02x}")
        if i < len(data) - 1:
            parts.append(",")
        if (i + 1) % 12 == 0 and i < len(data) - 1:
            parts.append("\n    ")
    return "".join(parts)


def write_byte_array(out_file, var_name: str, data: bytes):
    """Write a C byte array and its length constant."""
    hex_str = hex_dump(data)
    out_file.write(f"const uint8_t {var_name}[] = {{\n    {hex_str}\n}};\n")
    out_file.write(f"const size_t {var_name}_len = {len(data)};\n\n")


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <parasol_src_dir> <config_json> <out_dir>")
        sys.exit(1)

    parasol_src = sys.argv[1]
    config_json = sys.argv[2]
    out_dir = sys.argv[3]

    # Read config
    config = {}
    if os.path.exists(config_json):
        with open(config_json, "r") as f:
            config = json.load(f)

    title = config.get("title", "PARASOL")
    logo = config.get("logo", "/logo.png")
    favicon = config.get("favicon", "/favicon.ico")
    always_show_save = "1" if config.get("always_show_save", False) else "0"

    # Read and process index.html
    index_html_path = os.path.join(parasol_src, "index.html")
    with open(index_html_path, "r") as f:
        html = f.read()

    html = html.replace("{{TITLE}}", title)
    html = html.replace("{{LOGO}}", logo)
    html = html.replace("{{FAVICON}}", favicon)
    html = html.replace("{{ALWAYS_SHOW_SAVE}}", always_show_save)

    # Read JS and CSS
    with open(os.path.join(parasol_src, "app.min.js"), "r") as f:
        js = f.read()
    with open(os.path.join(parasol_src, "pico.jade.min.css"), "r") as f:
        css = f.read()

    # Gzip each asset
    html_gz = gzip.compress(html.encode("utf-8"), compresslevel=9)
    js_gz = gzip.compress(js.encode("utf-8"), compresslevel=9)
    css_gz = gzip.compress(css.encode("utf-8"), compresslevel=9)

    os.makedirs(out_dir, exist_ok=True)

    # Write prsl_assets.h
    header_path = os.path.join(out_dir, "prsl_assets.h")
    with open(header_path, "w") as f:
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
    print(f"Wrote {header_path}")

    # Write prsl_assets.c
    source_path = os.path.join(out_dir, "prsl_assets.c")
    with open(source_path, "w") as f:
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
    print(f"Wrote {source_path}")


if __name__ == "__main__":
    main()
