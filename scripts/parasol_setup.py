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


def generate_assets(parasol_dir):
    """Generate prsl_assets.h and prsl_assets.c by invoking the existing CMake script."""
    src_dir = os.path.join(parasol_dir, "src")
    assets_h = os.path.join(src_dir, "prsl_assets.h")
    assets_c = os.path.join(src_dir, "prsl_assets.c")

    if os.path.exists(assets_h) and os.path.exists(assets_c):
        return

    cmake_script = os.path.join(parasol_dir, "cmake", "generate_assets.cmake")
    config_path = "lib/reduzent/parasol_config.json"

    import subprocess
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


# ── Main ─────────────────────────────────────────────────────────
parasol_dirs = find_parasol_dirs()
if parasol_dirs:
    for parasol_dir in parasol_dirs:
        print(f"[parasol] Processing {parasol_dir}")
        generate_assets(parasol_dir)
        patch_prsl_store_h(parasol_dir)
        patch_prsl_h(parasol_dir)
        patch_prsl_cpp(parasol_dir)
else:
    print("[parasol] parasol library not found in libdeps (first build?)")
