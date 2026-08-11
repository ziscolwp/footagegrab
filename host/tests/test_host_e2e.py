"""End-to-end: spawn the real host process, speak native messaging over pipes,
enqueue two segments against a stubbed yt-dlp, and watch both jobs finish."""

import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HOST = Path(__file__).resolve().parents[1] / "footagegrab_host.py"

STUB_YTDLP = """#!/bin/bash
# Minimal yt-dlp stand-in: honors -o, prints progress like the real thing.
out=""
prev=""
for a in "$@"; do
  if [ "$prev" = "-o" ]; then out="$a"; fi
  prev="$a"
done
echo "[download]  10.0% of ~10.00MiB"
echo "[download]  60.0% of ~10.00MiB"
printf 'fake video bytes' > "$out"
echo "[download] 100% of 10.00MiB"
exit 0
"""


def frame(message):
    data = json.dumps(message).encode()
    return struct.pack("<I", len(data)) + data


class HostE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.out_dir = home / "footage"
        self.out_dir.mkdir()
        stub = home / "ytdlp-stub"
        stub.write_text(STUB_YTDLP)
        stub.chmod(0o755)
        (home / "config.json").write_text(json.dumps({
            "output_dir": str(self.out_dir),
            "ytdlp_path": str(stub),
            "ffmpeg_path": "/bin/ls",  # only existence is checked in this test
        }))
        env = dict(os.environ, FOOTAGEGRAB_HOME=str(home))
        self.proc = subprocess.Popen(
            [sys.executable, str(HOST)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
        )

    def tearDown(self):
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.tmp.cleanup()

    def read_msg(self):
        header = self.proc.stdout.read(4)
        self.assertEqual(len(header), 4, "host closed pipe unexpectedly")
        (length,) = struct.unpack("<I", header)
        return json.loads(self.proc.stdout.read(length).decode())

    def send(self, message):
        self.proc.stdin.write(frame(message))
        self.proc.stdin.flush()

    def test_ping_enqueue_two_segments_history(self):
        self.assertEqual(self.read_msg().get("type"), "hello")

        self.send({"id": 1, "type": "ping"})
        deadline = time.time() + 15
        ping = None
        while time.time() < deadline and ping is None:
            msg = self.read_msg()
            if msg.get("re") == 1:
                ping = msg
        self.assertTrue(ping and ping["ok"], f"ping failed: {ping}")

        self.send({
            "id": 2, "type": "enqueue",
            "url": "https://www.youtube.com/watch?v=test123",
            "video_id": "test123", "title": "Oprah: The Interview",
            "mode": "segments",
            "segments": [{"start": 42, "end": 78.5}, {"start": 100, "end": 120}],
        })

        ack = None
        done_states = {}
        deadline = time.time() + 20
        while time.time() < deadline:
            msg = self.read_msg()
            if msg.get("re") == 2:
                ack = msg
                self.assertTrue(msg["ok"], f"enqueue rejected: {msg}")
                self.assertEqual(len(msg["jobs"]), 2)
            elif msg.get("type") == "job_update":
                job = msg["job"]
                if job["state"] in ("done", "failed", "canceled"):
                    done_states[job["id"]] = job
            if ack and len(done_states) == 2:
                break
        self.assertEqual(len(done_states), 2, "both jobs should reach a terminal state")
        for job in done_states.values():
            self.assertEqual(job["state"], "done", f"job failed: {job.get('error')}")
            self.assertTrue(Path(job["file"]).exists(), "output file must exist")
            self.assertIn("Oprah The Interview", Path(job["file"]).name)

        names = sorted(Path(j["file"]).name for j in done_states.values())
        self.assertEqual(len(set(names)), 2, "segment files must not collide")
        # default template numbers parts per video, in mark order
        self.assertEqual(names, ["Oprah The Interview 1.mp4", "Oprah The Interview 2.mp4"])

        # invalid enqueue is rejected with a human message, not a crash
        self.send({"id": 3, "type": "enqueue",
                   "url": "https://www.youtube.com/watch?v=x",
                   "mode": "segments", "segments": [{"start": 10, "end": 9}]})
        while True:
            msg = self.read_msg()
            if msg.get("re") == 3:
                self.assertFalse(msg["ok"])
                self.assertIn("Out must be after In", msg["error"])
                break

        # history survived on disk
        self.send({"id": 4, "type": "get_history"})
        while True:
            msg = self.read_msg()
            if msg.get("re") == 4:
                self.assertTrue(msg["ok"])
                self.assertEqual(len(msg["history"]), 2)
                break


if __name__ == "__main__":
    unittest.main()
