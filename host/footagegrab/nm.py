"""Chrome native messaging framing: 4-byte little-endian length + UTF-8 JSON."""

import json
import struct
import sys
import threading

# Chrome rejects messages from the host larger than 1 MB; we stay far below that,
# but refuse absurd inbound lengths so a corrupt stream can't make us allocate GBs.
MAX_INBOUND = 32 * 1024 * 1024


class NativeMessagingIO:
    """Blocking reader / thread-safe writer over the stdio pipes Chrome gives us."""

    def __init__(self, stdin=None, stdout=None):
        self._in = stdin if stdin is not None else sys.stdin.buffer
        self._out = stdout if stdout is not None else sys.stdout.buffer
        self._write_lock = threading.Lock()

    def read(self):
        """Return the next decoded message, or None on EOF / broken stream."""
        header = self._read_exact(4)
        if header is None:
            return None
        (length,) = struct.unpack("<I", header)
        if length == 0 or length > MAX_INBOUND:
            return None
        data = self._read_exact(length)
        if data is None:
            return None
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def write(self, message):
        data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self._write_lock:
            self._out.write(struct.pack("<I", len(data)))
            self._out.write(data)
            self._out.flush()

    def _read_exact(self, n):
        chunks = []
        remaining = n
        while remaining > 0:
            chunk = self._in.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
