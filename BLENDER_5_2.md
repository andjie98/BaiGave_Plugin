# Blender 5.2 compatibility fork

Windows x64, tested on Blender **5.2.2 LTS**, Python **3.13.13**, NumPy **2.3.4**.
This is an experimental compatibility fork, not an upstream release.

## Installation

Build/download `BaiGave_Plugin-1.1.0-blender5.2-windows-x64.zip` and use
Blender Preferences → Add-ons → Install from Disk, then enable **BaiGave's Tool**.
The ZIP is intentionally a legacy add-on package, with a `BaiGave_Plugin` root.
Do not install GitHub's automatic source ZIP: it lacks the private runtime.

Use the BaiGave sidebar to add your own Minecraft client JAR / mod JARs and
resource packs. Game JARs are **not** redistributed in the new release ZIP.
The original workflows and Minecraft version assumptions (mostly 1.20.x)
remain; this does not add support for newer Minecraft formats.

## Compatibility approach

- Blender retains its own Python 3.13 and NumPy 2 installation.
- Amulet Core 1.9.47 and its native dependencies run in a bundled, isolated
  CPython 3.11.9 worker. This avoids loading incompatible Python 3.11 DLLs into
  Blender or forcing NumPy 1 into Blender's interpreter.
- RPyC 6.0.2 communicates only over inherited anonymous pipes, with no TCP
  listener, remote download on enable, or pickle deserialization enabled.
- Containers are copied before invoking native NBT constructors; serialized
  NBT bytes are written by the host instead of passing file handles across ABIs.
- Worker processes and world handles are closed when the add-on is disabled.
- TOML reading uses the standard library. Resource initialization and image
  pixel updates run on Blender's main thread. Scene properties are removed
  on disable and recreated on enable.
- Schematic export encodes palette indices as Sponge VarInts, including IDs
  above 127. Cache and export paths follow the installed add-on directory.

## Build

From a Windows x64 checkout, with Git, Python and pip >= 22.3:

```powershell
python tools/build_release.py --prepare
```

The builder verifies the embedded Python archive's SHA-256, installs the pinned
`requirements-runtime.txt` packages into the private runtime, and packages the
runtime and dependency license metadata. Subsequent builds can omit `--prepare`.
Python and library licenses remain in `runtime/` and `vendor/` in the ZIP.
Old wheels and `site-packages.zip` are excluded.

## Validation

Provide the Minecraft 1.20.1 client JAR in `mods/` (the upstream checkout includes
one), build the runtime, and run:

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py
```

Checks cover registration, NBT scalar/container round trips, Block construction,
Sponge schematic export/read/import, material loading and evaluated geometry (two cubes: 16 vertices, 12 faces),
130 palette entries, the NBT structure import operator, creation of a test Java
world, writing/reading a stair block with properties, and disable/enable cycles.
Fixtures are written to the checkout's `schem/` and `saves/compat_test_world/`.

Large maps, all mod combinations, optional rigs/sky presets, and the upstream
multiprocess workflow have not been exhaustively tested. Per-block cross-process
calls can add overhead on large maps. This release is Windows x64 only.
