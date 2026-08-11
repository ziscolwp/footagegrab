#!/usr/bin/env python3
"""Diagnose a FootageGrab install without touching Chrome.

  python3 host/selftest.py               # health report: tools, config, folder
  python3 host/selftest.py --roundtrip   # spawn the host, speak native messaging
  python3 host/selftest.py --roundtrip /path/to/launcher   # test via launcher
"""

import json
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from footagegrab import config, system  # noqa: E402


def frame(message):
    data = json.dumps(message).encode("utf-8")
    return struct.pack("<I", len(data)) + data


def read_frames(stream, count, timeout_hint=""):
    out = []
    for _ in range(count):
        header = stream.read(4)
        if len(header) < 4:
            raise SystemExit(f"host closed the pipe early {timeout_hint}")
        (length,) = struct.unpack("<I", header)
        out.append(json.loads(stream.read(length).decode("utf-8")))
    return out


def roundtrip(target):
    proc = subprocess.Popen(
        target, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    try:
        proc.stdin.write(frame({"id": 1, "type": "ping"}))
        proc.stdin.flush()
        hello, reply = read_frames(proc.stdout, 2, "(check logs/host.log)")
        assert hello.get("type") == "hello", f"expected hello, got {hello}"
        assert reply.get("ok") is True, f"ping failed: {reply}"
        h = reply["health"]
        print("native messaging roundtrip: OK")
        print(f"  host version : {reply.get('host_version')}")
        print(f"  yt-dlp       : {h['ytdlp']['version'] or 'NOT FOUND'}")
        print(f"  ffmpeg       : {h['ffmpeg']['version'] or 'NOT FOUND'}")
        print(f"  output folder: {h['output']['path']} (writable={h['output']['writable']})")
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def report():
    config.augment_path()
    cfg = config.load()
    h = system.health(cfg)
    ok = True
    for tool in ("ytdlp", "ffmpeg"):
        info = h[tool]
        mark = "OK " if info["found"] else "MISSING"
        ok = ok and info["found"]
        print(f"[{mark}] {tool}: {info['version'] or 'install with: brew install ' + tool.replace('ytdlp', 'yt-dlp')}")
    out = h["output"]
    mark = "OK " if out["writable"] else "FAIL"
    ok = ok and out["writable"]
    print(f"[{mark}] output folder: {out['path']}")
    print(f"[INFO] config: {config.config_path()}")
    print(f"[INFO] logs:   {h['logs']}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    if "--roundtrip" in sys.argv:
        idx = sys.argv.index("--roundtrip")
        launcher = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else None
        target = [launcher] if launcher else [sys.executable, str(Path(__file__).parent / "footagegrab_host.py")]
        roundtrip(target)
    else:
        report()
