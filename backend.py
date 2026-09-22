"""Isolate Amulet's Python 3.11 / NumPy 1 ABI from Blender's Python 3.13."""
import atexit
import os
from pathlib import Path
import subprocess
import threading
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


def varint_bytes(values):
    """Sponge BlockData stores VarInts, not one byte per palette index."""
    result = []
    for value in values:
        value = int(value)
        if value < 0:
            raise ValueError("Palette indices must be nonnegative")
        while value > 127:
            byte = (value & 127) | 128
            result.append(byte - 256)
            value >>= 7
        result.append(value)
    return result
