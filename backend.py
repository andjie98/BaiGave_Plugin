"""Isolate Amulet's Python 3.11 / NumPy 1 ABI from Blender's Python 3.13."""
import atexit
import os
from pathlib import Path
import subprocess
import threading
import json
import zlib
from types import SimpleNamespace
import rpyc
from .pipe_stream import PipeStream
from rpyc.core.channel import Channel

_connection = None
_process = None
_lock = threading.RLock()


def connection():
    global _connection, _process
    with _lock:
        if _connection is None or _connection.closed:
            root = Path(__file__).parent
            python = root / "runtime" / "python.exe"
            if not python.is_file():
                raise RuntimeError("Missing BaiGave runtime. Install the Windows Blender 5.2 release ZIP.")
            _process = subprocess.Popen(
                [str(python), "-u", str(root / "backend_server.py")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            _connection = rpyc.connect_channel(
                Channel(PipeStream(_process.stdout, _process.stdin)),
                config={"allow_public_attrs": True, "sync_request_timeout": 300})
        return _connection


def close():
    global _connection, _process
    if _connection is not None:
        _connection.close()
        _connection = None
    if _process is not None:
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.terminate()
            _process.wait(timeout=5)
        _process = None


atexit.register(close)


class Module:
    def __init__(self, name):
        self.name = name

    def __getattr__(self, name):
        return getattr(connection().root.module(self.name), name)

    def load_level(self, path):
        return connection().root.load_level(os.fspath(path))


amulet = Module("amulet")
amulet_nbt = Module("amulet_nbt")


class RenderBlock:
    """A translated Java state used only by the visual mesh builders."""
    def __init__(self, state, extras=()):
        self.state = state
        self.extra_blocks = tuple(RenderBlock(value) for value in extras)

    def __str__(self):
        return self.state


def is_block(value):
    return isinstance(value, RenderBlock) or isinstance(value, amulet.api.block.Block)


class RenderRegion:
    def __init__(self, palette, cells):
        self.palette = [RenderBlock(*item) for item in palette]
        self.cells = {(x, y, z): self.palette[index] for x, y, z, index in cells}
        self.air = RenderBlock("minecraft:air")
        self.translation_manager = SimpleNamespace(get_version=self.get_version)

    def get_version(self, platform, version):
        if (platform, tuple(version)) != ("java", (1, 20, 4)):
            raise ValueError("Render snapshot is translated to Java 1.20.4 only")
        return SimpleNamespace(block=SimpleNamespace(from_universal=lambda block: (block, None, False)))

    def get_block(self, x, y, z, dimension):
        if dimension != "main":
            raise ValueError(dimension)
        return self.cells.get((x, y, z), self.air)


def render_region(level, minimum, maximum):
    data = connection().root.render_region(level, tuple(minimum), tuple(maximum))
    return RenderRegion(*json.loads(zlib.decompress(data)))


def constructor(module, name):
    def create(*args, **kwargs):
        return connection().root.construct(module, name, args, kwargs)
    return create


Block = constructor("amulet.api.block", "Block")
for _name in ("TAG_Compound", "TAG_Int", "TAG_Byte", "TAG_String", "TAG_Long",
              "TAG_Double", "TAG_Float", "TAG_Short", "TAG_List", "ByteArrayTag",
              "IntArrayTag", "ShortTag"):
    globals()[_name] = constructor("amulet_nbt", _name)


def save_nbt(tag, destination):
    data = connection().root.save_nbt(tag)
    if hasattr(destination, "write"):
        destination.write(data)
    else:
        Path(destination).write_bytes(data)


def save_legacy_schematic(source, destination):
    """Rewrite a Sponge .schem as the legacy .schematic WorldEdit 6.x reads.

    :return: (path written, names of blocks with no 1.12.2 equivalent)
    """
    written, unmapped = connection().root.schem_to_schematic(
        os.fspath(source), os.fspath(destination))
    # rpyc hands collections back as proxies; copy before Blender touches them.
    return str(written), [str(name) for name in unmapped]


def make_sponge_schem(width, height, length, palette_names, block_data):
    """Ask the worker to assemble a Sponge .schem and return the finished bytes.

    Building the NBT tag from here would make every palette write a separate
    round trip over the pipe; the worker does it in one call instead.
    """
    return connection().root.make_sponge_schem(
        int(width), int(height), int(length),
        [str(name) for name in palette_names], bytes(block_data))


def varint_bytes(values):
    """Sponge BlockData stores VarInts, not one byte per palette index."""
    result = bytearray()
    for value in values:
        value = int(value)
        if value < 0:
            raise ValueError("Palette indices must be nonnegative")
        while value > 127:
            result.append((value & 127) | 128)
            value >>= 7
        result.append(value)
    return bytes(result)
