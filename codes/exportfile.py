from ..backend import save_nbt, save_legacy_schematic, varint_bytes, make_sponge_schem
import array
import os
import re
import shutil
import tempfile
import bpy
from ..backend import amulet
from ..backend import Block
from ..backend import TAG_Compound, TAG_Int, ByteArrayTag ,IntArrayTag,ShortTag,TAG_String
from .functions.tip import ShowMessageBox

# 把模型烤成 blockid 点云的那个修改器；带它的对象必须读求值后的网格。
BAKE_MODIFIER = '模型转换'
# 方块编号写在点云的这个顶点属性上，0 表示空气。
BLOCK_ID_ATTRIBUTE = 'blockid'


def safe_filename(name):
    """把用户输入当文件名用之前先收拾干净，避免写出 .schem.schem 这类名字。"""
    stem = os.path.basename((name or "").strip())
    for suffix in (".schematic", ".schem", ".nbt"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    stem = re.sub(r'[\\/:*?"<>|]', "_", stem).strip(". ")
    return stem or "schem"


def block_objects():
    """导出/计算要以哪些对象为准。

    导入算子把对象建好后就取消选中了，这时候按“没选中任何东西”处理会直接
    崩在 min() 上；所以选择为空时退回到场景里所有带 blockid 的对象。
    """
    selected = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
    if selected:
        return selected
    return [obj for obj in bpy.context.scene.objects
            if obj.type == 'MESH'
            and (BLOCK_ID_ATTRIBUTE in obj.data.attributes
                 or any(m.name == BAKE_MODIFIER for m in obj.modifiers))]


def collect_blocks(objects=None):
    """收集 {世界坐标: 方块编号}。

    带 ``模型转换`` 修改器的对象读求值后的网格（那个修改器本身就是在造
    点云），其余直接读原始网格。
    """
    if objects is None:
        objects = block_objects()
    result = {}
    for obj in objects:
        if obj.type != 'MESH':
            continue
        if any(m.name == BAKE_MODIFIER for m in obj.modifiers):
            data = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
        else:
            data = obj.data
        if BLOCK_ID_ATTRIBUTE not in data.attributes:
            continue
        attribute = data.attributes[BLOCK_ID_ATTRIBUTE].data
        for vertex in data.vertices:
            index = vertex.index
            if index >= len(attribute):
                break
            try:
                blockid = int(attribute[index].value)
            except (TypeError, ValueError):
                continue
            if blockid == 0:
                continue
            coord = tuple(int(c) for c in (obj.matrix_world @ vertex.co))
            result.setdefault(coord, blockid)
    return result


def unescape_block_name(name):
    """还原旧版 register.py 用 re.escape() 写进 Blocks.py 的反斜杠。

    老版本把方块名当正则转义之后存进映射表，``cobblestone_wall[east=low]``
    就变成了 ``cobblestone_wall\\[east=low\\]``，导出的 palette 里全是游戏
    认不出来的名字。新导入的数据已经是干净的，这里顺手兼容旧的 .blend。
    """
    if "\\" not in name:
        return name
    return re.sub(r"\\(.)", r"\1", name)


def block_id_names():
    """读取 Blocks.py 里注册的编号→方块名表；读不出来就返回 None。"""
    text_data = bpy.data.texts.get("Blocks.py")
    if not text_data:
        return None
    try:
        table = eval(text_data.as_string())
    except Exception:
        return None
    return {unescape_block_name(name): index for name, index in table.items()}


class OpenSaves_FileManagerOperator(bpy.types.Operator):
    bl_idname = "baigave.open_saves_folder_s"
    bl_label = "打开文件管理器"

    def execute(self, context):
        # 构建路径
        folderpath = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),"saves")

        # 打开文件管理器并导航到指定路径
        bpy.ops.wm.path_open(filepath=folderpath)

        return {'FINISHED'}

class OpenFileManagerOperator(bpy.types.Operator):
    bl_idname = "baigave.opem_schem_folder"
    bl_label = "打开文件管理器"

    def execute(self, context):
        # 构建路径
        folderpath = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),"schem")

        # 打开文件管理器并导航到指定路径
        bpy.ops.wm.path_open(filepath=folderpath)

        return {'FINISHED'}
class ExportSchem(bpy.types.Operator):
    """导出选定的区域为.schem文件"""
    bl_idname = "baigave.export_schem"
    bl_label = "导出.schem文件"
    vertex_dict = {} 
    block_id_name_map = {}  # 创建一个字典来存储 ID 和方块名称的映射
    filename ="schem"

    def execute(self, context):
        self.filename = safe_filename(context.scene.schem_filename)
        # 选择为空时 collect_blocks 会退回到场景里所有带 blockid 的对象，
        # 所以导入完直接点导出也能work；真一个方块都没有才报错退出。
        self.vertex_dict = collect_blocks()
        if not self.vertex_dict:
            ShowMessageBox(
                "没有可导出的方块。\n\n请先选中要导出的物体 —— 导入进来的结构"
                "就是场景里那个以文件名为名字的对象。",
                "白给的插件", icon='ERROR')
            return {'CANCELLED'}

        block_id_name_map = block_id_names()
        if not block_id_name_map:
            ShowMessageBox("未注册方块，无法导出。", "白给的插件", icon='ERROR')
            return {'CANCELLED'}
        self.block_id_name_map = block_id_name_map

        fmt = context.scene.export_format
        native_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "schem")

        # 只要低版本：中间那份 .schem 没有存在意义，写在临时目录里，转完就删。
        if fmt == "legacy":
            return self.export_legacy_only(context, native_dir)

        schem_path = self.export_schem(context)
        message = "文件导出成功！\n" + schem_path
        if fmt == "both":
            message = self.export_legacy(context, schem_path, message)
        ShowMessageBox(message,"白给的插件",link_text="点击这里前往导出文件夹", link_operator=OpenFileManagerOperator)
        return {'FINISHED'}

    def legacy_dir(self, context, fallback_dir):
        """用户填了输出目录就用它，否则退回给定的默认目录。"""
        target_dir = bpy.path.abspath(context.scene.legacy_schematic_dir).strip()
        return target_dir or fallback_dir

    def legacy_path(self, context, fallback_dir, stem):
        return os.path.join(
            self.legacy_dir(context, fallback_dir), stem + ".schematic")

    def export_legacy(self, context, schem_path, message):
        """Also write the legacy .schematic WorldEdit 6.x (Minecraft 1.12.2) loads.

        Amulet translates the 1.20 palette down to 1.12.2 numeric block ids and
        metadata; blocks that never existed before 1.13 come out as air.
        """
        destination = self.legacy_path(
            context, os.path.dirname(schem_path), self.filename)
        try:
            _, unmapped = save_legacy_schematic(schem_path, destination)
        except Exception as exc:
            return message + "\n\n.schematic 导出失败：" + str(exc)
        message += "\n已同时导出 legacy .schematic：\n" + destination
        return message + missing_blocks_note(unmapped)

    def export_legacy_only(self, context, native_dir):
        """只导出 .schematic：中间 .schem 写在临时目录，转换完立刻删掉。"""
        destination = self.legacy_path(context, native_dir, self.filename)
        staging = tempfile.mkdtemp(prefix="baigave_export_")
        try:
            schem_path = self.export_schem(context, folder=staging)
            _, unmapped = save_legacy_schematic(schem_path, destination)
        except Exception as exc:
            ShowMessageBox("导出 .schematic 失败：\n" + str(exc),
                           "白给的插件", icon='ERROR')
            return {'CANCELLED'}
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        message = "文件导出成功！\n" + destination
        ShowMessageBox(message + missing_blocks_note(unmapped), "白给的插件",
                       link_text="点击这里前往导出文件夹",
                       link_operator=OpenFileManagerOperator)
        return {'FINISHED'}

    def export_schem(self, context, folder=None):
        if not self.vertex_dict:
            # 正常流程里 execute 已经拦掉了，这里兜底，免得再崩在 min() 上
            raise ValueError("没有可导出的方块：选中对象里没有读到任何 blockid")

        names = list(self.block_id_name_map.keys())
        positions = self.vertex_dict

        min_x = min(coord[0] for coord in positions)
        max_x = max(coord[0] for coord in positions)
        min_y = min(coord[1] for coord in positions)
        max_y = max(coord[1] for coord in positions)
        min_z = min(coord[2] for coord in positions)
        max_z = max(coord[2] for coord in positions)

        width = max_x - min_x + 1
        length = max_y - min_y + 1
        height = max_z - min_z + 1

        # palette 和体素数组全在本地填，最后一次性把字节流交给 worker。
        # 老写法每放一个方块都要跨进程问一次 Palette（两万多个方块就是五万
        # 多次管道往返），Blender 主线程一直卡在 RPC 上，界面看着就是假死。
        palette_names = ["minecraft:air"]
        palette_slots = {"minecraft:air": 0}
        block_data = array.array("i", bytes(4 * length * width * height))
        for (x, y, z), blockid in positions.items():
            index = int(blockid)
            name = names[index] if 0 <= index < len(names) else "minecraft:air"
            slot = palette_slots.get(name)
            if slot is None:
                slot = len(palette_names)
                palette_slots[name] = slot
                palette_names.append(name)
            block_data[((z - min_z) * length + (y - min_y)) * width + (x - min_x)] = slot

        self.vertex_dict = {}

        if folder is None:
            folder = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "schem")
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, self.filename + ".schem")  # 设置你想要保存的文件路径
        data = make_sponge_schem(width, height, length, palette_names,
                                 varint_bytes(block_data))
        with open(file_path, "wb") as f:
            f.write(data)
        return file_path

def missing_blocks_note(unmapped, limit=8):
    """Report blocks that never existed before 1.13 and therefore became air."""
    if not unmapped:
        return ""
    preview = "、".join(unmapped[:limit])
    if len(unmapped) > limit:
        preview += "…"
    return "\n\n注意：%d 种方块在 1.12.2 里不存在，已变成空气：\n%s" % (len(unmapped), preview)


class ConvertSchemToSchematic(bpy.types.Operator):
    """把已有的 .schem 转成 WorldEdit 6.x (Minecraft 1.12.2) 能读的 legacy .schematic"""
    bl_idname = "baigave.convert_schem_to_schematic"
    bl_label = "转换 .schem 为 .schematic"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH") # type: ignore
    filter_glob: bpy.props.StringProperty(default="*.schem", options={'HIDDEN'}) # type: ignore
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement) # type: ignore

    def execute(self, context):
        paths = [os.path.join(os.path.dirname(self.filepath), f.name) for f in self.files]
        if not paths:
            paths = [self.filepath]
        target_dir = bpy.path.abspath(context.scene.legacy_schematic_dir).strip()
        written, failed, unmapped = [], [], set()
        for path in paths:
            stem = os.path.splitext(os.path.basename(path))[0]
            destination = os.path.join(target_dir or os.path.dirname(path), stem + ".schematic")
            try:
                _, missing = save_legacy_schematic(path, destination)
            except Exception as exc:
                failed.append("%s: %s" % (os.path.basename(path), exc))
                continue
            unmapped.update(missing)
            written.append(destination)
        message = "转换完成，共 %d 个文件。\n" % len(written) + "\n".join(written)
        message += missing_blocks_note(sorted(unmapped))
        if failed:
            message += "\n\n失败：\n" + "\n".join(failed)
        ShowMessageBox(message, "白给的插件", link_text="点击这里前往导出文件夹", link_operator=OpenFileManagerOperator)
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class Calculate_Size(bpy.types.Operator):
    """计算大小"""
    bl_idname = "baigave.calculate_size"
    bl_label = "计算大小"
    vertex_dict = {} 
    def execute(self, context):
        self.vertex_dict = collect_blocks()
        if not self.vertex_dict:
            ShowMessageBox("没有可计算的方块，请先选中要计算的物体。",
                           "白给的插件", icon='ERROR')
            return {'CANCELLED'}

        min_coords = [min(coord[i] for coord in self.vertex_dict) for i in range(3)]
        max_coords = [max(coord[i] for coord in self.vertex_dict) for i in range(3)]

        # 计算长、宽和高
        length = max_coords[0] - min_coords[0] + 1
        width = max_coords[1] - min_coords[1] + 1
        height = max_coords[2] - min_coords[2] + 1
        size = (length, width, height)

        context.scene.schem_size = size
        context.scene.schem_location = min_coords
        return {'FINISHED'}

class ExportToSave(bpy.types.Operator):
    """导出到存档"""
    bl_idname = "baigave.export_to_save"
    bl_label = "导出到存档"
    vertex_dict = {} 
    block_id_name_map = {}  # 创建一个字典来存储 ID 和方块名称的映射
    foldername =""

    def execute(self, context):
        self.foldername = context.scene.save_list
        # 先校验再开存档，免得导不出来还留着一个没关的 level
        self.vertex_dict = collect_blocks()
        if not self.vertex_dict:
            ShowMessageBox(
                "没有可导出的方块。\n\n请先选中要导出的物体 —— 导入进来的结构"
                "就是场景里那个以文件名为名字的对象。",
                "白给的插件", icon='ERROR')
            return {'CANCELLED'}

        block_id_name_map = block_id_names()
        if not block_id_name_map:
            ShowMessageBox("未注册方块，无法导出。", "白给的插件", icon='ERROR')
            return {'CANCELLED'}
        self.block_id_name_map = block_id_name_map

        worldpath = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),"saves",self.foldername)
        level = amulet.load_level(worldpath)

        # 遍历坐标表
        block_id_name_map = list(self.block_id_name_map.keys())
        try:
            for coordinates, block_id in self.vertex_dict.items():
                x, y, z = coordinates
                if not 0 <= block_id < len(block_id_name_map):
                    continue
                # 获取方块名称
                block_name = block_id_name_map[block_id]
                if block_name != "minecraft:air":
                    namespace, path = block_name.split(':')
                    properties = {}
                    match = re.search(r'([^[]*)\[.*\]', path)
                    # 处理带有方块属性的情况
                    if match:
                        path = match.group(1)
                        properties_str = match.group(0)[len(path)+1:-1]
                        for prop in properties_str.split(','):
                            key, value = prop.split('=')
                            properties[key] = TAG_String(value)
                        block = Block(namespace, path, properties)
                    else:
                        block = Block(namespace, path)
                    # 在世界中放置方块
                    level.set_version_block(x, z, -y, "minecraft:overworld",
                                            ("java", (1, 20, 4)), block)
            # 保存修改后的世界
            level.save()
        finally:
            level.close()
        ShowMessageBox("文件导出成功！","白给的插件",link_text="点击这里前往导出文件夹", link_operator=OpenSaves_FileManagerOperator)
        return {'FINISHED'}
       
classes=[OpenFileManagerOperator,OpenSaves_FileManagerOperator,ExportSchem,ConvertSchemToSchematic,Calculate_Size,ExportToSave]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    
def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)