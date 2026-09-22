"""Private Amulet worker, communicating over inherited pipes (no network port)."""
import sys
import importlib
import rpyc
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from pipe_stream import PipeStream
from rpyc.core.channel import Channel

protocol_out = sys.stdout
sys.stdout = sys.stderr
import amulet
import amulet_nbt


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


connection = Backend._connect(
    Channel(PipeStream(sys.stdin.buffer, protocol_out.buffer)),
    config={"allow_public_attrs": True, "allow_setattr": True,
            "allow_delattr": True, "sync_request_timeout": 300})
connection.serve_all()
