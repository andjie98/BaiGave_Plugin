"""Windows anonymous-pipe stream using only the Python standard library."""
import ctypes
from ctypes import wintypes
import msvcrt
import os
from rpyc.core.stream import Stream
from rpyc.lib import Timeout

_peek = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
_peek.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                  wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPDWORD]
_peek.restype = wintypes.BOOL


class PipeStream(Stream):
    MAX_IO_CHUNK = 65536

    def __init__(self, incoming, outgoing):
        self.incoming, self.outgoing = incoming, outgoing

    @property
    def closed(self):
        return self.incoming.closed

    def close(self):
        self.incoming.close()
        self.outgoing.close()

    def fileno(self):
        return self.incoming.fileno()

    def poll(self, timeout):
        timeout = Timeout(timeout)
        while not self.closed:
            available = wintypes.DWORD()
            if not _peek(msvcrt.get_osfhandle(self.fileno()), None, 0, None,
                         ctypes.byref(available), None):
                raise EOFError("Amulet worker pipe closed")
            if available.value:
                return True
            if timeout.expired():
                return False
            timeout.sleep(0.001)
        raise EOFError("Amulet worker pipe closed")

    def read(self, count):
        chunks = []
        while count:
            data = os.read(self.fileno(), min(count, 65536))
            if not data:
                raise EOFError("Amulet worker exited")
            chunks.append(data)
            count -= len(data)
        return b"".join(chunks)

    def write(self, data):
        try:
            while data:
                count = os.write(self.outgoing.fileno(), data[:65536])
                if not count:
                    raise EOFError("Amulet worker pipe closed")
                data = data[count:]
        except (OSError, ValueError) as exc:
            raise EOFError("Amulet worker pipe closed") from exc
