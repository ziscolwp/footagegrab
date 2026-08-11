import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab.compat import (bitrate_for_height, build_transcode_args,
                                find_ffprobe, parse_progress_line)


class BitrateTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(bitrate_for_height(2160), "50M")
        self.assertEqual(bitrate_for_height(4320), "50M")
        self.assertEqual(bitrate_for_height(1440), "28M")
        self.assertEqual(bitrate_for_height(1080), "14M")
        self.assertEqual(bitrate_for_height(720), "8M")
        self.assertEqual(bitrate_for_height(480), "5M")


class TranscodeArgsTests(unittest.TestCase):
    def test_videotoolbox_4k(self):
        argv = build_transcode_args("/f/ffmpeg", "in.mp4", "out.mp4",
                                    height=2160, acodec="aac")
        self.assertIn("h264_videotoolbox", argv)
        self.assertEqual(argv[argv.index("-b:v") + 1], "50M")
        self.assertEqual(argv[argv.index("-c:a") + 1], "copy")
        self.assertIn("yuv420p", argv)  # 10-bit HDR sources must land 8-bit
        self.assertEqual(argv[-1], "out.mp4")

    def test_opus_audio_gets_reencoded(self):
        argv = build_transcode_args("/f/ffmpeg", "a", "b", height=2160, acodec="opus")
        self.assertEqual(argv[argv.index("-c:a") + 1], "aac")

    def test_libx264_fallback(self):
        argv = build_transcode_args("/f/ffmpeg", "a", "b", height=1080,
                                    acodec="aac", encoder="libx264")
        self.assertIn("libx264", argv)
        self.assertIn("-crf", argv)
        self.assertNotIn("h264_videotoolbox", argv)


class ProgressParseTests(unittest.TestCase):
    def test_out_time_ms_is_microseconds(self):
        self.assertAlmostEqual(parse_progress_line("out_time_ms=2500000", 5.0), 0.5)
        self.assertEqual(parse_progress_line("out_time_ms=99999999", 5.0), 1.0)

    def test_non_progress_lines_ignored(self):
        self.assertIsNone(parse_progress_line("frame=42", 5.0))
        self.assertIsNone(parse_progress_line("out_time_ms=1", 0))
        self.assertIsNone(parse_progress_line("out_time_ms=abc", 5.0))


class FfprobeTests(unittest.TestCase):
    def test_prefers_sibling_of_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "ffmpeg").touch()
            (d / "ffprobe").touch()
            self.assertEqual(find_ffprobe(d / "ffmpeg"), str(d / "ffprobe"))


if __name__ == "__main__":
    unittest.main()
