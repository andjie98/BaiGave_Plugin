"""导出路径回归测试。

针对的真实故障：导入完成后插件取消选中，此时点「导出结构」/「计算大小」会崩在
``ValueError: min() iterable argument is empty``（exportfile.py 的 min(x_values)）。

跑法::

    blender --background --factory-startup --python-exit-code 1 \
        --python tests/blender_export_regression.py -- <结构文件>

不给参数时用仓库里的 ``schem/palette130.schem``。
"""
import os
import shutil
import sys
import importlib.util

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(REPO))

# 必须显式从仓库加载：Blender 的 addons 目录里也装了一份同名插件，直接
# ``import BaiGave_Plugin`` 会命中那一份，测的就不是这里的改动了。
spec = importlib.util.spec_from_file_location(
    "BaiGave_Plugin", os.path.join(REPO, "__init__.py"),
    submodule_search_locations=[REPO])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

from BaiGave_Plugin import backend  # noqa: E402
from BaiGave_Plugin.codes.exportfile import collect_blocks, safe_filename  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
STRUCT = args[0] if args else os.path.join(REPO, "schem", "palette130.schem")
assert os.path.isfile(STRUCT), "结构文件不存在: %s" % STRUCT

SCHEM_DIR = os.path.join(REPO, "schem")
LEGACY_DIR = os.path.join(SCHEM_DIR, "regression_legacy")
NAME = "regression_export"
STEM = safe_filename(NAME + ".schem")          # 故意带后缀，验证会被剥掉
SPONGE = os.path.join(SCHEM_DIR, STEM + ".schem")
LEGACY = os.path.join(LEGACY_DIR, STEM + ".schematic")

for path in (SPONGE, LEGACY):
    if os.path.exists(path):
        os.remove(path)
if os.path.isdir(LEGACY_DIR):
    shutil.rmtree(LEGACY_DIR)

# ---------------------------------------------------------------- 文件名清洗
assert safe_filename("zhongqui.schem") == "zhongqui"
assert safe_filename("zhongqui.schematic") == "zhongqui"
assert safe_filename("") == "schem"
assert safe_filename("   ") == "schem"
assert "/" not in safe_filename("a/b")
print("SAFE_FILENAME_OK")

module.register()

# ------------------------------------------------------------------- 导入
assert bpy.ops.baigave.import_schem(filepath=STRUCT) == {'FINISHED'}

# 关键前提：导入算子不选中任何东西 —— 这正是原来崩溃的场景。
bpy.ops.object.select_all(action='DESELECT')
assert not bpy.context.selected_objects, bpy.context.selected_objects
print("NOTHING_SELECTED_AFTER_IMPORT_OK")

scene = bpy.context.scene
scene.schem_filename = NAME + ".schem"
scene.export_format = "both"
scene.legacy_schematic_dir = LEGACY_DIR

# --------------------------------------------------------------- 计算大小
result = bpy.ops.baigave.calculate_size()
assert result == {'FINISHED'}, result
size = tuple(scene.schem_size)
assert all(d > 0 for d in size), size
print("CALCULATE_SIZE_OK", size)

# --------------------------------------------------------------- 导出结构
expected_blocks = len(collect_blocks())
assert expected_blocks > 0, expected_blocks

result = bpy.ops.baigave.export_schem()
assert result == {'FINISHED'}, result
assert os.path.isfile(SPONGE), "没有写出 %s" % SPONGE
assert os.path.isfile(LEGACY), "没有写出 %s" % LEGACY
print("EXPORT_WITHOUT_SELECTION_OK")
print("  sponge  :", os.path.getsize(SPONGE), "bytes ->", SPONGE)
print("  legacy  :", os.path.getsize(LEGACY), "bytes ->", LEGACY)

# ------------------------------------------------- 导出的内容要和导入的一致
# 读原始 NBT 校验：远程 Structure 对象不开放 platform 之类的属性。
root = backend.amulet_nbt.load(SPONGE)
assert int(root["Version"].value) == 2, root["Version"].value
assert int(root["DataVersion"].value) == 3465, root["DataVersion"].value
palette = [str(key) for key in root["Palette"]]
assert "minecraft:air" in palette, palette[:5]
assert len(palette) > 2, palette

raw = [int(byte) & 0xFF for byte in root["BlockData"]]
decoded, value, shift = [], 0, 0
for byte in raw:
    value |= (byte & 0x7F) << shift
    if byte & 0x80:
        shift += 7
    else:
        decoded.append(value)
        value = shift = 0
placed = sum(1 for index in decoded if index != 0)
assert len(decoded) == size[0] * size[1] * size[2], (len(decoded), size)
assert placed == expected_blocks, (placed, expected_blocks)
print("READBACK_OK", "palette=%d" % len(palette), "blocks=%d" % placed)

# --------------------------------------------------- 空场景必须干净地拒绝
keep = [obj for obj in bpy.context.scene.objects
        if obj.type == 'MESH' and 'blockid' in obj.data.attributes]
assert keep, "没找到带 blockid 的对象"
for obj in keep:
    bpy.data.objects.remove(obj, do_unlink=True)
before = os.path.getsize(SPONGE)

assert bpy.ops.baigave.export_schem() == {'CANCELLED'}
assert os.path.getsize(SPONGE) == before, "空导出竟然改写了文件"
assert bpy.ops.baigave.calculate_size() == {'CANCELLED'}
print("EMPTY_SELECTION_REJECTED_OK")

# ------------------------------------- 缺 Blocks.py 也要干净地拒绝而不是崩
assert bpy.ops.baigave.import_schem(filepath=STRUCT) == {'FINISHED'}
bpy.ops.object.select_all(action='DESELECT')
bpy.data.texts.remove(bpy.data.texts["Blocks.py"])
assert bpy.ops.baigave.export_schem() == {'CANCELLED'}
print("MISSING_BLOCKS_PY_REJECTED_OK")

module.unregister()
print("EXPORT_REGRESSION_ALL_OK")
