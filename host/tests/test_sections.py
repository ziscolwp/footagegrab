import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab.sections import build_download_args, section_spec


def build(**kwargs):
    defaults = dict(url="https://www.youtube.com/watch?v=abc", out_path="/tmp/out.mp4")
    defaults.update(kwargs)
    return build_download_args(**defaults)


class SectionSpecTests(unittest.TestCase):
    def test_spec_format(self):
        self.assertEqual(section_spec(42, 78.5), "*42-78.5")
        self.assertEqual(section_spec(0, 10), "*0-10")


class BuildArgsTests(unittest.TestCase):
    def test_full_download_has_no_sections(self):
        argv = build(mode="full")
        self.assertNotIn("--download-sections", argv)
        self.assertIn("--merge-output-format", argv)
        self.assertEqual(argv[-1], "https://www.youtube.com/watch?v=abc")
        self.assertEqual(argv[argv.index("-o") + 1], "/tmp/out.mp4")

    def test_segment_download(self):
        argv = build(mode="segment", start=42, end=78.5)
        i = argv.index("--download-sections")
        self.assertEqual(argv[i + 1], "*42-78.5")
        self.assertNotIn("--force-keyframes-at-cuts", argv)

    def test_accurate_mode_forces_keyframes(self):
        argv = build(mode="segment", start=1, end=2, accurate=True)
        self.assertIn("--force-keyframes-at-cuts", argv)

    def test_quality_sort_strings(self):
        self.assertIn("vcodec:h264,res,acodec:m4a", build(quality="best"))
        self.assertIn("vcodec:h264,res:1080,acodec:m4a", build(quality="1080"))
        self.assertIn("vcodec:h264,res:720,acodec:m4a", build(quality="720"))

    def test_cookies_flag(self):
        argv = build(cookies_browser="brave")
        self.assertEqual(argv[argv.index("--cookies-from-browser") + 1], "brave")
        self.assertNotIn("--cookies-from-browser", build(cookies_browser="none"))
        self.assertNotIn("--cookies-from-browser", build(cookies_browser=None))

    def test_ffmpeg_location(self):
        argv = build(ffmpeg_path="/opt/homebrew/bin/ffmpeg")
        self.assertEqual(argv[argv.index("--ffmpeg-location") + 1], "/opt/homebrew/bin/ffmpeg")

    def test_rejections(self):
        with self.assertRaises(ValueError):
            build(quality="4k")
        with self.assertRaises(ValueError):
            build(mode="segment", start=10, end=10)
        with self.assertRaises(ValueError):
            build(mode="segment", start=None, end=5)
        with self.assertRaises(ValueError):
            build(cookies_browser="firefox")


if __name__ == "__main__":
    unittest.main()
