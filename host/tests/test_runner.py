"""Retry-ladder behavior of DownloadRunner around the rung-2 fallback.

A scripted yt-dlp stub fails every attempt with a transient 403; the fallback
and duration probe are patched so no real downloads or network happen.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab import prefetch
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
                "output_dir": tmp, "quality": "max", "accurate_cut": False,
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


if __name__ == "__main__":
    unittest.main()
