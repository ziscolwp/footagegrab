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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab import config, runner  # noqa: E402
from footagegrab.router import Router  # noqa: E402

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


class _FakeQueue:
    """Records submitted jobs without running them — enough for router tests
    that only need to inspect the reply, not watch a job finish."""

    def __init__(self):
        self.jobs = []

    def submit(self, job):
        self.jobs.append(job)
        return job


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
        # A separate in-process Router against the same FOOTAGEGRAB_HOME, for
        # tests that check message handling directly rather than round-trip
        # through the subprocess pipe.
        self._old_home = os.environ.get("FOOTAGEGRAB_HOME")
        os.environ["FOOTAGEGRAB_HOME"] = str(home)
        self.queue = _FakeQueue()
        self.router = Router(self.queue, runner=None)

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("FOOTAGEGRAB_HOME", None)
        else:
            os.environ["FOOTAGEGRAB_HOME"] = self._old_home
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

    # -- destination selection messages (router, in-process) ----------------

    def test_set_destination_selects_an_existing_folder(self):
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        cfg, b = config.add_destination(str(Path(self.tmp.name) / "b"))
        reply = self.router.handle({"id": 1, "type": "set_destination", "dest_id": a["id"]})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["config"]["destination_id"], a["id"])

    def test_set_destination_rejects_an_unknown_id(self):
        reply = self.router.handle({"id": 1, "type": "set_destination", "dest_id": "nope"})
        self.assertFalse(reply["ok"])
        self.assertIn("unknown destination", reply["error"])

    def test_remove_destination_reports_the_new_selection(self):
        # This fixture's config.json already migrated a legacy output_dir into
        # one destination (see setUp) — clear it first so "the new selection"
        # unambiguously means the one this test adds, not that leftover entry.
        (Path(self.tmp.name) / "config.json").write_text(json.dumps({
            "destinations": [], "destination_id": "",
        }))
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        cfg, b = config.add_destination(str(Path(self.tmp.name) / "b"))
        reply = self.router.handle({"id": 1, "type": "remove_destination", "dest_id": b["id"]})
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["config"]["destination_id"], a["id"])

    def test_choose_folder_message_is_gone(self):
        reply = self.router.handle({"id": 1, "type": "choose_folder"})
        self.assertFalse(reply["ok"])
        self.assertIn("unknown message type", reply["error"])

    def test_enqueue_carries_a_per_job_destination_override(self):
        folder = Path(self.tmp.name) / "a"
        folder.mkdir()
        cfg, a = config.add_destination(str(folder))
        reply = self.router.handle({
            "id": 1, "type": "enqueue", "mode": "full",
            "url": "https://youtube.com/watch?v=abc", "destination_id": a["id"],
        })
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["jobs"][0]["destination_id"], a["id"])

    def test_enqueue_rejects_an_unknown_destination_override(self):
        # config.selected_destination falls back to entries[0] when the
        # selected id doesn't match anything — fine for the config's own
        # destination_id, but an *override* that doesn't match a real
        # destination must fail loudly rather than silently redirect to
        # destination #1.
        config.add_destination(str(Path(self.tmp.name) / "a"))
        reply = self.router.handle({
            "id": 1, "type": "enqueue", "mode": "full",
            "url": "https://youtube.com/watch?v=abc", "destination_id": "nope",
        })
        self.assertFalse(reply["ok"])
        self.assertIn("nope", reply["error"])

    def test_enqueue_refuses_when_no_destination_is_set(self):
        # Same reason as test_remove_destination_reports_the_new_selection:
        # the fixture's config.json migrates a legacy destination in, so it
        # must be cleared explicitly for this to test an empty list.
        (Path(self.tmp.name) / "config.json").write_text(json.dumps({
            "destinations": [], "destination_id": "",
        }))
        reply = self.router.handle({"id": 1, "type": "enqueue", "mode": "full",
                                    "url": "https://youtube.com/watch?v=abc"})
        self.assertFalse(reply["ok"])
        self.assertIn("no destination set", reply["error"])

    @unittest.skipIf(
        sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
        "chmod(0o500) is a no-op on Windows, and W_OK is always true for root",
    )
    def test_enqueue_refuses_an_unwritable_destination_and_names_it(self):
        blocked = Path(self.tmp.name) / "blocked"
        blocked.mkdir()
        blocked.chmod(0o500)
        try:
            config.add_destination(str(blocked))
            reply = self.router.handle({"id": 1, "type": "enqueue", "mode": "full",
                                        "url": "https://youtube.com/watch?v=abc"})
            self.assertFalse(reply["ok"])
            self.assertIn(str(blocked), reply["error"])
        finally:
            blocked.chmod(0o700)

    def test_enqueue_refuses_a_missing_destination_and_does_not_create_it(self):
        # config.validate_output_dir must only check, never mkdir — creating
        # an unmounted external-volume path here would silently redirect
        # every future grab to the internal disk once the real drive mounts.
        missing = Path(self.tmp.name) / "not-yet-mounted"
        config.add_destination(str(missing))
        reply = self.router.handle({"id": 1, "type": "enqueue", "mode": "full",
                                    "url": "https://youtube.com/watch?v=abc"})
        self.assertFalse(reply["ok"])
        self.assertIn(str(missing), reply["error"])
        self.assertFalse(missing.exists(), "enqueue must not create the destination")

    def test_startup_sweep_removes_a_leftover_staging_folder(self):
        # Happy-path counterpart to test_startup_sweep_failure_does_not_block_
        # boot below: a real, valid destination with a .fg-tmp left behind by
        # a crash must actually be swept on the next boot, not just fail to
        # crash the host when the sweep itself errors out.
        home2 = Path(self.tmp.name) / "home3"
        home2.mkdir()
        dest = home2 / "footage"
        dest.mkdir()
        stage = dest / ".fg-tmp"
        stage.mkdir()
        orphan = stage / "orphan.mp4.part"
        orphan.write_bytes(b"junk")
        # Old enough to count as a crash leftover — fresh files are spared
        # in case a draining sibling host is still writing them.
        old = time.time() - (runner.STAGE_SWEEP_MIN_AGE + 60)
        os.utime(orphan, (old, old))
        (home2 / "config.json").write_text(json.dumps({
            "destinations": [{"id": "d1", "label": "footage", "path": str(dest)}],
            "destination_id": "d1",
        }))
        env = dict(os.environ, FOOTAGEGRAB_HOME=str(home2))
        proc = subprocess.Popen(
            [sys.executable, str(HOST)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
        )
        try:
            header = proc.stdout.read(4)
            self.assertEqual(len(header), 4, "host crashed before sending hello")
            (length,) = struct.unpack("<I", header)
            hello = json.loads(proc.stdout.read(length).decode())
            self.assertEqual(hello.get("type"), "hello")
            # The sweep runs before "hello" is written, so it has already
            # happened by the time this is observed.
            self.assertFalse(stage.exists(), "leftover .fg-tmp must be swept at startup")
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def test_startup_sweep_failure_does_not_block_boot(self):
        # A malformed stored path (an embedded NUL byte) makes
        # config.ensure_output_dir raise ValueError, not OSError. The startup
        # sweep in footagegrab_host.py must be best-effort against any
        # exception, or the host dies before answering a single message and
        # the user just sees a dead extension.
        home2 = Path(self.tmp.name) / "home2"
        home2.mkdir()
        bad_path = "/tmp/x" + chr(0) + "y"
        (home2 / "config.json").write_text(json.dumps({
            "destinations": [{"id": "d1", "label": "bad", "path": bad_path}],
            "destination_id": "d1",
        }))
        env = dict(os.environ, FOOTAGEGRAB_HOME=str(home2))
        proc = subprocess.Popen(
            [sys.executable, str(HOST)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
        )
        try:
            header = proc.stdout.read(4)
            self.assertEqual(len(header), 4, "host crashed before sending hello")
            (length,) = struct.unpack("<I", header)
            hello = json.loads(proc.stdout.read(length).decode())
            self.assertEqual(hello.get("type"), "hello")

            # get_config, not ping: ping's reply folds in system.health(),
            # which has this same OSError-only gap independently of the
            # startup sweep — using it here would fail for an unrelated
            # reason instead of proving the host booted.
            proc.stdin.write(frame({"id": 1, "type": "get_config"}))
            proc.stdin.flush()
            header = proc.stdout.read(4)
            self.assertEqual(len(header), 4, "host closed the pipe before answering a message")
            (length,) = struct.unpack("<I", header)
            reply = json.loads(proc.stdout.read(length).decode())
            self.assertTrue(reply.get("ok"), reply)
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    unittest.main()
