"""Windows-branch units that run anywhere (sys.platform patched)."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab import compat  # noqa: E402


class EncoderSelection(unittest.TestCase):
    def test_per_platform_candidates(self):
        self.assertEqual(compat.encoder_candidates("darwin"),
                         ("h264_videotoolbox", "libx264"))
        self.assertEqual(compat.encoder_candidates("win32"),
                         ("h264_nvenc", "libx264"))
        self.assertEqual(compat.encoder_candidates("linux"), ("libx264",))

    def test_nvenc_transcode_args(self):
        argv = compat.build_transcode_args(
            "ffmpeg", "in.webm", "out.mp4", height=2160, acodec="opus",
            encoder="h264_nvenc")
        self.assertIn("h264_nvenc", argv)
        self.assertIn("50M", argv)
        self.assertIn("aac", argv)  # opus audio re-encoded


class WindowsAppHome(unittest.TestCase):
    def test_app_home_uses_appdata(self):
        from footagegrab import config
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.dict(os.environ, {"APPDATA": "/tmp/fake-appdata"}, clear=False), \
             mock.patch.dict(os.environ):
            os.environ.pop("FOOTAGEGRAB_HOME", None)
            home = config.app_home()
        self.assertEqual(str(home), str(Path("/tmp/fake-appdata") / "FootageGrab"))

    def test_footagegrab_home_override_still_wins(self):
        from footagegrab import config
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.dict(os.environ, {"FOOTAGEGRAB_HOME": "/tmp/fg-override"}):
            self.assertEqual(str(config.app_home()), "/tmp/fg-override")


if __name__ == "__main__":
    unittest.main()
