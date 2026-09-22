# Blender 5.2 compatibility fork

Windows x64, tested on Blender **5.2.2 LTS**, Python **3.13.13**, NumPy **2.3.4**.
This is an experimental compatibility fork, not an upstream release.

Based on [BaiGave/BaiGave_Plugin](https://github.com/BaiGave/BaiGave_Plugin) by **BaiGave** (AGPL-3.0, see `LICENSE`). Fork maintained by **andjie98** (<https://github.com/andjie98/BaiGave_Plugin>); modified portions are released under the same AGPL-3.0 licence, original copyright and credits retained.

## Installation

Build/download `BaiGave_Plugin-1.1.5-blender5.2-windows-x64.zip` and use
Blender Preferences → Add-ons → Install from Disk, then enable **BaiGave's Tool**.
The ZIP is intentionally a legacy add-on package, with a `BaiGave_Plugin` root.
Do not install GitHub's automatic source ZIP: it lacks the private runtime.

Use the BaiGave sidebar to add your own Minecraft client JAR / mod JARs and
resource packs. Game JARs are **not** redistributed in the new release ZIP.
The original workflows and Minecraft version assumptions (mostly 1.20.x)
remain; this does not add support for newer Minecraft formats.

## Legacy schematic support (1.1.1)

The structure import button accepts both `.schem` and legacy `.schematic` files,
including mixed multi-selection. Legacy numeric block IDs and metadata are
translated by Amulet's Java 1.12.2 reader (for example, wool 35:14 becomes red wool).
The directory picker lists both formats. Bounds are converted from Amulet's
exclusive maximum to the mesh builder's inclusive maximum, and files are closed
on failure as well as success. Export writes Sponge `.schem` plus a legacy twin
(see below).

Tested with stone, glass and red wool, including metadata, coordinates, actual
mesh faces and texture loading. Custom legacy mod numeric-ID mappings and entity
rendering are not added by this change.

## Legacy schematic export (1.1.2)

WorldEdit 7 / Minecraft 1.13 introduced the Sponge `.schem` format; older
WorldEdit — including 6.1.9, the last build for 1.12.2 — only reads the MCEdit
`.schematic` format, which stores numeric block ids and metadata instead of a
palette of names. A `.schem` therefore cannot be dropped into a 1.12.2 server's
`plugins/WorldEdit/schematics` folder, and the export button never wrote there
anyway: it lands in the add-on's own `schem/` directory.

The export button now also writes a `.schematic` twin, translated by Amulet's
legacy writer to Java 1.12.2 (palette indices above 127 included). The
`.schematic` output directory is a scene property; leave it empty to write
beside the `.schem`, or point it at `plugins/WorldEdit/schematics` to load the
structure in game with `//schem load <name>`. A separate **转换已有 .schem 为
.schematic** button converts structures exported before this change, and accepts
a multi-selection.

Blocks with no 1.12.2 equivalent (copper, deepslate, everything added from 1.16
onwards, and unknown mod blocks) come out as air. Because PyMCTranslate reports
only non-vanilla blocks, the count is derived by comparing the source and
converted block arrays, so the popup lists exactly what was dropped. The
comparison is a plain NumPy pass — no per-block cross-process calls.

## Export format selector (1.1.5)

Writing a legacy twin by default meant every export produced two files, even
for users who only ever target a modern server. The boolean
`同时导出 .schematic` is replaced by a three-way **导出格式** selector:

| Value | Output | Target |
| --- | --- | --- |
| `sponge` | `<name>.schem` only | WorldEdit 7+ / Minecraft 1.13+ |
| `legacy` | `<name>.schematic` only | WorldEdit 6.x / Minecraft 1.12.2 |
| `both` | both files | either |

`sponge` is the default, matching the add-on's behaviour before legacy export
existed. The `.schematic` directory field only shows up for `legacy` and
`both`. In `legacy` mode the intermediate `.schem` — Amulet's converter reads
one as its input — is written to a `tempfile.mkdtemp()` staging directory and
deleted in a `finally` block, so `schem/` never collects stray files.

Note that the scene property is renamed, so an old `.blend` carrying
`export_legacy_schematic` simply falls back to the new default.

## Resource-pack priority fix (1.1.5)

`get_file_path` walks `mod_list` in order and returns the first hit, so the list
order really is the priority — that part of the README holds. The resource-pack
branch, however, accumulated the base path inside its loop:

```python
path = filepath + directory
for d in directories_r:
    path = path + "\\" + d + "\\assets\\" + mod   # path never resets
```

The second resource pack resolved to `<pack1>\assets\<mod>\<pack2>\assets\<mod>`,
so everything below the first entry was silently unreachable — moving a pack to
the top of the list had no effect past position one. Both copies of the pattern
(`codes/functions/get_data.py` and the CTM lookup in `codes/block.py`) now use a
separate `base_path` inside the loop.

Also fixed: the README table-of-contents anchor for the blockstate JSON section
was misspelled (`#导入blockstae...`), so the link did not jump anywhere.

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
- The legacy `.schematic` twin is written by the worker process, so no Amulet
  object crosses into Blender's interpreter; only the path and the list of
  dropped block names come back.

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
world, writing/reading a stair block with properties, legacy `.schematic` export
through the worker (java 1.12.2, numeric ids, nothing dropped) and the convert
operator, and disable/enable cycles.
Fixtures are written to the checkout's `schem/` and `saves/compat_test_world/`.

Large maps, all mod combinations, optional rigs/sky presets, and the upstream
multiprocess workflow have not been exhaustively tested. Per-block cross-process
calls can add overhead on large maps. This release is Windows x64 only.
