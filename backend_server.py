"""Private Amulet worker, communicating over inherited pipes (no network port)."""
import sys
import importlib
import os
import rpyc
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pipe_stream import PipeStream
from rpyc.core.channel import Channel

protocol_out = sys.stdout
sys.stdout = sys.stderr
import amulet
import amulet_nbt
import json
import numpy
import zlib

AIR_NAMES = ("minecraft:air", "minecraft:cave_air", "minecraft:void_air")


def decode_varints(raw):
    """Sponge BlockData stores palette indices as VarInts."""
    values = []
    value = shift = 0
    for byte in raw:
        value |= (int(byte) & 0x7F) << shift
        if int(byte) & 0x80:
            shift += 7
        else:
            values.append(value)
            value = shift = 0
    return values


def legacy_block_ids(compound):
    """Merge Blocks with AddBlocks, the way Amulet reads the legacy format."""
    ids = compound.get_byte_array("Blocks").np_array.astype(numpy.uint16)
    if "AddBlocks" in compound:
        add = compound.get_byte_array("AddBlocks").np_array
        high = (
            numpy.concatenate([[(add & 0xF0) >> 4], [add & 0x0F]])
            .T.ravel()
            .astype(numpy.uint16)
            << 8
        )[: ids.size]
        ids = ids + high
    return ids


def lost_blocks(src, dst):
    """Names of blocks solid in `src` that came out as air in `dst`.

    Translation silently drops anything 1.12.2 has no equivalent for, and only
    non-vanilla blocks get a log line, so compare the two files instead. Sponge
    BlockData and legacy Blocks/Data share the same YZX flat order, which makes
    this a straight array compare.
    """
    source = amulet_nbt.load(src).compound
    converted = amulet_nbt.load(dst).compound
    names = {tag.py_int: name for name, tag in source["Palette"].items()}
    source_air = {index for index, name in names.items() if name in AIR_NAMES}
    raw = source.get_byte_array("BlockData").np_array.tobytes()
    source_index = numpy.array(decode_varints(numpy.frombuffer(raw, dtype=numpy.uint8)),
                               dtype=numpy.int32)
    block_ids = legacy_block_ids(converted)
    if source_index.size != block_ids.size:
        return []
    data = converted.get_byte_array("Data").np_array
    missing = ~numpy.isin(source_index, list(source_air)) & (block_ids == 0) & (data == 0)
    return sorted({names[index] for index in numpy.unique(source_index[missing])})


def byte_array(data):
    """ByteArrayTag from a buffer; a list of ten million ints is not an option."""
    array = numpy.frombuffer(data, dtype=numpy.int8) if isinstance(data, (bytes, bytearray)) \
        else numpy.asarray(data, dtype=numpy.int8)
    try:
        return amulet_nbt.ByteArrayTag(array)
    except Exception:
        return amulet_nbt.ByteArrayTag([int(value) for value in array])


def materialize(value):
    """Copy RPC containers into this interpreter for Cython constructors."""
    if isinstance(value, dict):
        return {k: materialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [materialize(v) for v in value]
    if isinstance(value, tuple):
        return tuple(materialize(v) for v in value)
    return value


class Backend(rpyc.Service):
    def on_connect(self, conn):
        self.levels = []

    def on_disconnect(self, conn):
        for level in self.levels:
            try:
                level.close()
            except Exception:
                pass

    def exposed_module(self, name):
        if name not in ("amulet", "amulet_nbt", "amulet.api.block"):
            raise ValueError(name)
        return importlib.import_module(name)

    def exposed_construct(self, module, name, args, kwargs):
        return getattr(self.exposed_module(module), name)(
            *materialize(args), **materialize(kwargs))

    def exposed_load_level(self, path):
        level = amulet.load_level(path)
        self.levels.append(level)
        return level

    def exposed_save_nbt(self, tag):
        return tag.save_to()

    def exposed_make_sponge_schem(self, width, height, length, palette_names, block_data):
        """Assemble a whole Sponge .schem here and hand back the finished bytes.

        Building the tag from Blender makes every palette write an RPC round trip
        (measured at 6.5 ms each) and a 28k-block structure needs tens of
        thousands of them, which freezes the UI for minutes. The caller sends
        flat data instead, so only bytes travel over the pipe.
        """
        root = amulet_nbt.TAG_Compound({
            'DataVersion': amulet_nbt.TAG_Int(3465),
            'Version': amulet_nbt.TAG_Int(2),
            'Metadata': amulet_nbt.TAG_Compound({
                'WEOffsetX': amulet_nbt.TAG_Int(0),
                'WEOffsetY': amulet_nbt.TAG_Int(0),
                'WEOffsetZ': amulet_nbt.TAG_Int(0),
            }),
            'Palette': amulet_nbt.TAG_Compound({
                name: amulet_nbt.TAG_Int(index)
                for index, name in enumerate(palette_names)}),
            'PaletteMax': amulet_nbt.TAG_Int(len(palette_names)),
            'Length': amulet_nbt.ShortTag(length),
            'Height': amulet_nbt.ShortTag(height),
            'Width': amulet_nbt.ShortTag(width),
            'BlockData': byte_array(block_data),
            'Offset': amulet_nbt.IntArrayTag([0, 0, 0]),
        })
        return root.save_to()

    def exposed_schem_to_schematic(self, src, dst):
        """Rewrite a Sponge .schem as the legacy .schematic WorldEdit 6.x reads.

        WorldEdit 7 / Minecraft 1.13 introduced the Sponge format; anything older
        (the 1.12.2 line, WorldEdit 6.1.9) only understands the MCEdit format,
        which stores numeric block ids and data instead of a palette of names.
        Amulet's legacy schematic wrapper converts the palette for us when the
        structure is saved at version 1.12.2.

        :return: (path written, names of blocks that had no 1.12.2 equivalent)
        """
        from amulet.level.formats.schematic import SchematicFormatWrapper

        level = amulet.load_level(src)
        try:
            bounds = level.bounds("main")
            folder = os.path.dirname(os.path.abspath(dst))
            if folder:
                os.makedirs(folder, exist_ok=True)
            out = SchematicFormatWrapper(dst)
            out.create_and_open("java", (1, 12, 2), bounds, overwrite=True)
            try:
                for cx, cz in level.all_chunk_coords("main"):
                    out.commit_chunk(level.get_chunk(cx, cz, "main"), "main")
                out.save()
            finally:
                out.close()
        finally:
            level.close()
        return dst, lost_blocks(src, dst)

    def exposed_render_region(self, level, minimum, maximum):
        """Translate in-process and transfer one compressed, data-only snapshot."""
        version = level.translation_manager.get_version("java", (1, 20, 4))
        palette = []
        indices = {}
        cells = []
        for x in range(minimum[0], maximum[0]):
            for y in range(minimum[1], maximum[1]):
                for z in range(minimum[2], maximum[2]):
                    block = level.get_block(x, y, z, "main")
                    if block.base_name in ("air", "cave_air", "void_air"):
                        continue
                    modern = level.get_version_block(x, y, z, "main", ("java", (1, 20, 4)))[0]
                    extras = tuple(str(version.block.from_universal(extra)[0]) for extra in block.extra_blocks)
                    key = (str(modern), extras)
                    if key not in indices:
                        indices[key] = len(palette)
                        palette.append(key)
                    cells.append((x, y, z, indices[key]))
        return zlib.compress(json.dumps((palette, cells)).encode("utf8"))


connection = Backend._connect(
    Channel(PipeStream(sys.stdin.buffer, protocol_out.buffer)),
    config={"allow_public_attrs": True, "allow_setattr": True,
            "allow_delattr": True, "sync_request_timeout": 300})
connection.serve_all()
