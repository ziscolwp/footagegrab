# TODO: split by concern
"""Retry-ladder behavior of DownloadRunner around the rung-2 fallback.

A scripted yt-dlp stub fails every attempt with a transient 403; the fallback
and duration probe are patched so no real downloads or network happen.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab import config, prefetch, runner
from footagegrab.jobs import Job
from footagegrab.runner import DownloadRunner

STUB_403 = """#!/bin/bash
echo "$@" >> "{log}"
echo "ERROR: unable to download video data: HTTP Error 403: Forbidden" >&2
exit 1
"""


@unittest.skipIf(sys.platform == "win32", "bash stub")
class FallbackFailureLadderTests(unittest.TestCase):
    """After the full-download fallback fails, the runner must keep walking
    the client chain (android_vr, tv_downgraded) instead of giving up —
    unless the fallback error is permanent."""

    def _run(self, fallback_result):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "argv.log"
            stub = Path(tmp) / "ytdlp-stub"
            stub.write_text(STUB_403.format(log=log))
            stub.chmod(0o755)
            cfg = {
                "destinations": [{"id": "d1", "label": "test", "path": tmp}],
                "destination_id": "d1",
                "quality": "max", "accurate_cut": False,
                "compat_transcode": False, "cookies_browser": "none",
                "template_segment": "{title} {n}", "template_full": "{title} {n}",
                "ytdlp_path": str(stub), "ffmpeg_path": "/bin/ls",
            }
            runner = DownloadRunner(lambda: cfg)
            job = Job(url="https://www.youtube.com/watch?v=x", video_id="x",
                      title="Clip", mode="segment", start=1, end=5)
            with mock.patch.object(prefetch, "fetch_duration", return_value=60), \
                 mock.patch.object(DownloadRunner, "_run_fallback",
                                   return_value=fallback_result) as fb, \
                 mock.patch.object(DownloadRunner, "_sleep_unless_canceled",
                                   return_value=True):
                ok, error, final = runner.run(job)
            argv_lines = log.read_text() if log.exists() else ""
            return ok, error, fb.call_count, argv_lines

    def test_transient_fallback_failure_climbs_the_client_chain(self):
        ok, error, fallback_calls, argv = self._run(
            (False, "HTTP Error 403: Forbidden", ""))
        self.assertFalse(ok)
        self.assertEqual(fallback_calls, 1)
        self.assertEqual(argv.count("player_client=mweb"), 1)
        self.assertEqual(argv.count("player_client=android_vr"), 1)
        self.assertEqual(argv.count("player_client=tv_downgraded"), 1)

    def test_permanent_fallback_failure_stops_the_ladder(self):
        ok, error, fallback_calls, argv = self._run(
            (False, "This video is private", ""))
        self.assertFalse(ok)
        self.assertEqual(error, "This video is private")
        self.assertEqual(fallback_calls, 1)
        self.assertNotIn("player_client=android_vr", argv)
        self.assertNotIn("player_client=tv_downgraded", argv)


class DeliverAndSweepTests(unittest.TestCase):
    """Atomic delivery out of the staging folder, and crash cleanup."""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("FOOTAGEGRAB_HOME")
        os.environ["FOOTAGEGRAB_HOME"] = self.home.name

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("FOOTAGEGRAB_HOME", None)
        else:
            os.environ["FOOTAGEGRAB_HOME"] = self._old_home
        self.home.cleanup()

    def test_deliver_moves_a_staged_file_into_the_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            stage = config.ensure_stage_dir(dest)
            staged = stage / "clip.mp4"
            staged.write_bytes(b"data")
            r = runner.DownloadRunner(lambda: {})
            final = r._deliver(staged, dest)
            self.assertEqual(final, dest / "clip.mp4")
            self.assertTrue(final.is_file())
            self.assertFalse(staged.exists())

    def test_deliver_picks_a_new_name_single_threaded_when_one_already_exists(self):
        # Pins _deliver's single-threaded rename-around-a-collision behaviour
        # only. It does NOT test the concurrent-delivery guarantee its old
        # name implied: unique_path picks the name and os.replace lands the
        # file as two separate steps, leaving a known, deliberately accepted
        # TOCTOU window if two deliveries race for the same stem at once.
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            (dest / "clip.mp4").write_bytes(b"original")
            stage = config.ensure_stage_dir(dest)
            staged = stage / "clip.mp4"
            staged.write_bytes(b"new")
            r = runner.DownloadRunner(lambda: {})
            final = r._deliver(staged, dest)
            self.assertEqual(final.name, "clip_2.mp4")
            self.assertEqual((dest / "clip.mp4").read_bytes(), b"original")

    def test_find_output_ignores_full_and_h264_intermediates(self):
        # The staging folder is now shared between the fallback's whole-video
        # temp (<stem>.full.mp4) and the compat-transcode scratch file
        # (<stem>.h264tmp.mp4) — both satisfy _FINAL_EXTS and both match the
        # {stem}.* glob, so picking the *largest* match (as _find_output did)
        # can ship the wrong file. Without the fix, the 100-byte .full.mp4
        # intermediate wins over the real 10-byte .mkv output.
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            target = stage / "clip.mp4"
            (stage / "clip.full.mp4").write_bytes(b"x" * 100)
            (stage / "clip.h264tmp.mp4").write_bytes(b"x" * 50)
            (stage / "clip.mkv").write_bytes(b"y" * 10)
            found = runner.DownloadRunner._find_output(target)
            self.assertEqual(found, stage / "clip.mkv")

    def test_find_output_still_finds_the_fallbacks_own_sibling_extension(self):
        # _find_output(tmp_path) is itself called with tmp_path stem
        # "<clip>.full" (the fallback's whole-video temp target). The marker
        # exclusion above must not disqualify *that* stem's own legitimate
        # sibling-extension landing (yt-dlp merging to .mkv/.webm instead of
        # the requested .mp4) just because ".full" is baked into the stem.
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            target = stage / "clip.full.mp4"  # requested but never created
            (stage / "clip.full.mkv").write_bytes(b"z" * 10)
            found = runner.DownloadRunner._find_output(target)
            self.assertEqual(found, stage / "clip.full.mkv")

    def test_sweep_removes_leftover_staging_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            stage = config.ensure_stage_dir(dest)
            (stage / "orphan.mp4.part").write_bytes(b"junk")
            runner.sweep_stage_dir(dest)
            self.assertFalse(stage.exists())

    def test_sweep_also_removes_a_legacy_in_destination_staging_folder(self):
        # Older builds staged inside the destination; a crash there must
        # still be cleaned up after the upgrade.
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            legacy = dest / config.STAGE_DIR_NAME
            legacy.mkdir()
            (legacy / "orphan.mp4.part").write_bytes(b"junk")
            runner.sweep_stage_dir(dest)
            self.assertFalse(legacy.exists())

    def test_sweep_is_safe_when_there_is_nothing_to_sweep(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner.sweep_stage_dir(Path(tmp))  # must not raise


STUB_NOOP = """#!/bin/bash
exit 0
"""

# Finds the value that follows -o and writes a .part sibling, sleeps briefly
# (giving the test time to observe mid-download state), then renames it into
# place and exits 0 — a slow-motion successful yt-dlp run.
STUB_SLOW_SUCCESS = """#!/bin/bash
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then
    out="$arg"
  fi
  prev="$arg"
done
echo -n "partial bytes" > "$out.part"
sleep {sleep}
mv "$out.part" "$out"
exit 0
"""

# Fails every attempt with a permanent (non-transient) error, after leaving a
# .part sibling behind — like a real yt-dlp crash mid-download. Logs argv so
# the test can pin the -o path it was actually given (staged vs. unstaged).
STUB_PERMANENT_FAILURE = """#!/bin/bash
echo "$@" >> "{log}"
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then
    out="$arg"
  fi
  prev="$arg"
done
echo -n "partial bytes" > "$out.part"
echo "ERROR: This video is private" >&2
exit 1
"""

# Segment attempts (--download-sections present) fail transiently, forcing
# the runner into the full-download+local-cut fallback; full attempts (used
# by both a plain full-mode grab and the fallback's whole-video temp) write
# real bytes to the requested output path and succeed.
STUB_SEGMENT_FAILS_FULL_SUCCEEDS = """#!/bin/bash
for arg in "$@"; do
  if [ "$arg" = "--download-sections" ]; then
    echo "ERROR: unable to download video data: HTTP Error 403: Forbidden" >&2
    exit 1
  fi
done
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then
    out="$arg"
  fi
  prev="$arg"
done
echo -n "full video bytes" > "$out"
exit 0
"""

# ffmpeg stand-in for the fallback's local cut: writes to its last argument
# (the destination the runner asked ffmpeg to cut into).
STUB_FFMPEG_CUT = """#!/bin/bash
last="${@: -1}"
echo -n "cut segment bytes" > "$last"
exit 0
"""


def _write_stub(path, script, **fmt):
    path.write_text(script.format(**fmt) if fmt else script)
    path.chmod(0o755)


def _base_cfg(tmp, ytdlp, ffmpeg):
    return {
        "destinations": [{"id": "d1", "label": "test", "path": tmp}],
        "destination_id": "d1",
        "quality": "max", "accurate_cut": False,
        "compat_transcode": False, "cookies_browser": "none",
        "template_segment": "{title} {n}", "template_full": "{title} {n}",
        "ytdlp_path": str(ytdlp), "ffmpeg_path": str(ffmpeg),
    }


@unittest.skipIf(sys.platform == "win32", "bash stub")
class RunEndToEndTests(unittest.TestCase):
    """Exercises the real run() entry point (not just _deliver in isolation)
    over the riskiest paths the staging/delivery change touches: the
    destination staying clean mid-download, a failed download leaving no
    trace, a bad staging folder being reported instead of raised, and the
    fallback's cut being delivered out of staging like everything else.

    Reuses FallbackFailureLadderTests' bash-stub-stands-in-for-yt-dlp
    harness rather than inventing a new one.
    """

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("FOOTAGEGRAB_HOME")
        os.environ["FOOTAGEGRAB_HOME"] = self.home.name

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("FOOTAGEGRAB_HOME", None)
        else:
            os.environ["FOOTAGEGRAB_HOME"] = self._old_home
        self.home.cleanup()

    def test_stage_dir_error_is_reported_not_raised(self):
        # A plain file sitting where the staging root should be makes
        # config.ensure_stage_dir's mkdir raise OSError. run() must catch it
        # and report a normal job failure — not let it escape to the caller
        # as an unhandled exception (jobs.py would surface that as an opaque
        # "internal error: [Errno ...]").
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as tools:
            dest = Path(tmp)
            config.stage_root().write_bytes(b"not a directory")
            noop = Path(tools) / "noop"
            _write_stub(noop, STUB_NOOP)
            cfg = _base_cfg(tmp, noop, noop)
            r = DownloadRunner(lambda: cfg)
            job = Job(url="https://www.youtube.com/watch?v=x", video_id="x",
                      title="Clip", mode="full")
            ok, error, final = r.run(job)
            self.assertFalse(ok)
            self.assertIn("staging folder unavailable", error)
            self.assertEqual(final, "")

    def test_bytes_are_staged_and_destination_holds_no_partial_name_mid_download(self):
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as tools:
            dest = Path(tmp)
            stub = Path(tools) / "ytdlp-stub"
            _write_stub(stub, STUB_SLOW_SUCCESS, sleep=0.4)
            cfg = _base_cfg(tmp, stub, "/bin/ls")
            r = DownloadRunner(lambda: cfg)
            job = Job(url="https://www.youtube.com/watch?v=x", video_id="x",
                      title="Clip", mode="full")
            result = {}
            t = threading.Thread(target=lambda: result.setdefault("out", r.run(job)))
            t.start()
            try:
                deadline = time.time() + 5
                observed_mid_download = False
                stage = config.stage_dir_for(dest)
                while time.time() < deadline and t.is_alive():
                    if stage.is_dir() and any(stage.iterdir()):
                        observed_mid_download = True
                        visible = [p.name for p in dest.iterdir() if p.name != ".fg-tmp"]
                        self.assertEqual(visible, [])
                        break
                    time.sleep(0.02)
            finally:
                t.join(timeout=5)
            self.assertTrue(observed_mid_download, "never observed staged bytes mid-download")
            ok, error, final = result["out"]
            self.assertTrue(ok, error)
            final_path = Path(final)
            self.assertEqual(final_path.parent, dest)
            self.assertTrue(final_path.is_file())

    def test_failed_download_leaves_destination_and_staging_clean(self):
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as tools:
            dest = Path(tmp)
            log = Path(tools) / "argv.log"
            stub = Path(tools) / "ytdlp-stub"
            _write_stub(stub, STUB_PERMANENT_FAILURE, log=log)
            cfg = _base_cfg(tmp, stub, "/bin/ls")
            r = DownloadRunner(lambda: cfg)
            job = Job(url="https://www.youtube.com/watch?v=x", video_id="x",
                      title="Clip", mode="full")
            ok, error, final = r.run(job)
            self.assertFalse(ok)
            self.assertEqual(final, "")
            # Pin staged behaviour directly, rather than only checking
            # emptiness (which a pre-staging runner, writing straight into
            # dest and relying on _cleanup_partials, would also satisfy):
            # the -o path the runner actually gave yt-dlp must sit inside
            # the staging folder, which must have been created for this run.
            stage = config.stage_dir_for(dest)
            argv = log.read_text()
            self.assertIn(str(stage), argv)
            self.assertTrue(stage.is_dir())
            self.assertEqual(list(stage.iterdir()), [])
            visible = [p.name for p in dest.iterdir() if p.name != ".fg-tmp"]
            self.assertEqual(visible, [])

    def test_fallback_cut_is_delivered_from_staging(self):
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as tools:
            dest = Path(tmp)
            ytdlp_stub = Path(tools) / "ytdlp-stub"
            _write_stub(ytdlp_stub, STUB_SEGMENT_FAILS_FULL_SUCCEEDS)
            ffmpeg_stub = Path(tools) / "ffmpeg-stub"
            _write_stub(ffmpeg_stub, STUB_FFMPEG_CUT)
            cfg = _base_cfg(tmp, ytdlp_stub, ffmpeg_stub)
            r = DownloadRunner(lambda: cfg)
            job = Job(url="https://www.youtube.com/watch?v=x", video_id="x",
                      title="Clip", mode="segment", start=1, end=5)
            with mock.patch.object(prefetch, "fetch_duration", return_value=60), \
                 mock.patch.object(DownloadRunner, "_sleep_unless_canceled",
                                   return_value=True):
                ok, error, final = r.run(job)
            self.assertTrue(ok, error)
            final_path = Path(final)
            self.assertTrue(final_path.is_file())
            self.assertEqual(final_path.parent, dest)
            self.assertNotIn(".fg-tmp", final_path.parts)
            self.assertEqual(final_path.read_bytes(), b"cut segment bytes")
            stage = config.stage_dir_for(dest)
            self.assertEqual(list(stage.iterdir()) if stage.is_dir() else [], [])

    def test_replace_failure_fails_the_job_and_leaves_no_trace(self):
        # Pins the spec's error-table row for os.replace failing (permissions,
        # vanished folder): the job must fail, the staged file must be gone,
        # the destination must be untouched, and the error must name it.
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as tools:
            dest = Path(tmp)
            stub = Path(tools) / "ytdlp-stub"
            _write_stub(stub, STUB_SLOW_SUCCESS, sleep=0)
            cfg = _base_cfg(tmp, stub, "/bin/ls")
            r = DownloadRunner(lambda: cfg)
            job = Job(url="https://www.youtube.com/watch?v=x", video_id="x",
                      title="Clip", mode="full")
            with mock.patch("footagegrab.runner.os.replace",
                             side_effect=OSError("permission denied")):
                ok, error, final = r.run(job)
            self.assertFalse(ok)
            self.assertEqual(final, "")
            self.assertIn(str(dest), error)
            visible = [p.name for p in dest.iterdir() if p.name != ".fg-tmp"]
            self.assertEqual(visible, [], "destination must be untouched")
            stage = config.stage_dir_for(dest)
            self.assertEqual(list(stage.iterdir()) if stage.is_dir() else [], [],
                              "staged file must be removed")

    def test_destination_override_on_the_job_redirects_the_delivered_file(self):
        # d1 stays the config's *selected* destination throughout — only the
        # job's own destination_id should determine where the file lands.
        # Asserting the override actually redirects (not just that the field
        # survives to_dict()) is what distinguishes "honoured" from "ignored".
        with tempfile.TemporaryDirectory() as d1, \
             tempfile.TemporaryDirectory() as d2, \
             tempfile.TemporaryDirectory() as tools:
            dest1, dest2 = Path(d1), Path(d2)
            stub = Path(tools) / "ytdlp-stub"
            _write_stub(stub, STUB_SLOW_SUCCESS, sleep=0)
            cfg = _base_cfg(d1, stub, "/bin/ls")
            cfg["destinations"].append({"id": "d2", "label": "other", "path": d2})
            r = DownloadRunner(lambda: cfg)
            job = Job(url="https://www.youtube.com/watch?v=x", video_id="x",
                      title="Clip", mode="full", destination_id="d2")
            ok, error, final = r.run(job)
            self.assertTrue(ok, error)
            final_path = Path(final)
            self.assertEqual(final_path.parent, dest2)
            self.assertEqual(list(dest1.glob("*.mp4")), [])


if __name__ == "__main__":
    unittest.main()
