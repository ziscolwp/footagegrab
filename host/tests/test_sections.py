import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab.sections import (
    FALLBACK_MAX_DURATION,
    build_download_args,
    build_local_cut_args,
    is_transient_error,
    plan_retry,
    section_spec,
)


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
        self.assertIn("res,vcodec:h264,acodec:m4a", build(quality="max"))
        self.assertIn("vcodec:h264,res:1080,acodec:m4a", build(quality="1080"))
        self.assertIn("vcodec:h264,res:720,acodec:m4a", build(quality="720"))

    def test_legacy_best_is_max(self):
        self.assertEqual(build(quality="best"), build(quality="max"))

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

    def test_player_client_flag(self):
        argv = build(player_client="web_safari")
        i = argv.index("--extractor-args")
        self.assertEqual(argv[i + 1], "youtube:player_client=web_safari")
        self.assertNotIn("--extractor-args", build())
        self.assertNotIn("--extractor-args", build(player_client=None))


class TransientErrorTests(unittest.TestCase):
    def test_transient_signatures_match(self):
        self.assertTrue(is_transient_error("ERROR: ffmpeg exited with code 8"))
        self.assertTrue(is_transient_error("HTTP Error 403: Forbidden"))
        self.assertTrue(is_transient_error("ERROR: unable to download video data: HTTP Error 403"))
        self.assertTrue(is_transient_error("fragment 3 not found, unable to continue"))
        self.assertTrue(is_transient_error("ERROR: Ffmpeg Exited With Code 8"))  # case-insensitive

    def test_permanent_errors_do_not_match(self):
        self.assertFalse(is_transient_error("Private video. Sign in if you've been granted access"))
        self.assertFalse(is_transient_error("Video unavailable"))
        self.assertFalse(is_transient_error("Sign in to confirm you're not a bot"))
        self.assertFalse(is_transient_error(""))
        self.assertFalse(is_transient_error(None))


class PlanRetryTests(unittest.TestCase):
    def test_first_failure_retries_with_rotated_client(self):
        plan = plan_retry(1, "segment")
        self.assertIsNotNone(plan)
        self.assertGreater(plan["delay"], 0)
        self.assertEqual(plan["client"], "web_safari")
        self.assertFalse(plan["try_fallback"])

    def test_second_failure_offers_fallback_for_segments_only(self):
        seg = plan_retry(2, "segment")
        self.assertTrue(seg["try_fallback"])
        self.assertIsNone(seg["client"])
        full = plan_retry(2, "full")
        self.assertFalse(full["try_fallback"])

    def test_third_failure_gives_up(self):
        self.assertIsNone(plan_retry(3, "segment"))
        self.assertIsNone(plan_retry(4, "full"))

    def test_fallback_cap_is_thirty_minutes(self):
        self.assertEqual(FALLBACK_MAX_DURATION, 1800)


class LocalCutTests(unittest.TestCase):
    def test_fast_cut_stream_copies(self):
        argv = build_local_cut_args("/bin/ffmpeg", "/t/full.mp4", "/t/out.mp4", 108.9, 127.8)
        self.assertEqual(argv[0], "/bin/ffmpeg")
        self.assertEqual(argv[argv.index("-ss") + 1], "108.9")
        self.assertEqual(argv[argv.index("-t") + 1], "18.9")
        self.assertEqual(argv[argv.index("-c") + 1], "copy")
        self.assertEqual(argv[-1], "/t/out.mp4")
        self.assertIn("-y", argv)

    def test_accurate_cut_reencodes(self):
        argv = build_local_cut_args("/bin/ffmpeg", "/t/full.mp4", "/t/out.mp4", 10, 20, accurate=True)
        self.assertNotIn("copy", argv)
        self.assertEqual(argv[argv.index("-c:v") + 1], "libx264")
        self.assertEqual(argv[argv.index("-c:a") + 1], "aac")

    def test_rejects_inverted_range(self):
        with self.assertRaises(ValueError):
            build_local_cut_args("/bin/ffmpeg", "/t/a.mp4", "/t/b.mp4", 20, 10)


if __name__ == "__main__":
    unittest.main()
