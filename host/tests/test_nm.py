import io
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab.nm import NativeMessagingIO


def frame(payload_bytes):
    return struct.pack("<I", len(payload_bytes)) + payload_bytes


class FramingTests(unittest.TestCase):
    def test_roundtrip(self):
        out = io.BytesIO()
        NativeMessagingIO(stdin=io.BytesIO(), stdout=out).write({"a": 1, "s": "héllo"})
        nm = NativeMessagingIO(stdin=io.BytesIO(out.getvalue()), stdout=io.BytesIO())
        self.assertEqual(nm.read(), {"a": 1, "s": "héllo"})

    def test_multiple_messages_in_stream(self):
        out = io.BytesIO()
        writer = NativeMessagingIO(stdin=io.BytesIO(), stdout=out)
        writer.write({"n": 1})
        writer.write({"n": 2})
        reader = NativeMessagingIO(stdin=io.BytesIO(out.getvalue()), stdout=io.BytesIO())
        self.assertEqual(reader.read(), {"n": 1})
        self.assertEqual(reader.read(), {"n": 2})
        self.assertIsNone(reader.read(), "EOF returns None")

    def test_truncated_and_garbage_streams(self):
        cases = [
            b"",                      # empty
            b"\x01\x00",              # short header
            frame(b"{not json")[:-2],  # truncated body
            frame(b"not json"),        # invalid json
            struct.pack("<I", 0),      # zero length
            struct.pack("<I", 2 ** 31),  # absurd length
        ]
        for raw in cases:
            nm = NativeMessagingIO(stdin=io.BytesIO(raw), stdout=io.BytesIO())
            self.assertIsNone(nm.read(), f"case {raw!r}")


if __name__ == "__main__":
    unittest.main()
