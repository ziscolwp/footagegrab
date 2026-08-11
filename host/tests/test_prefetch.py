import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from footagegrab import prefetch  # noqa: E402

US = "\x1f"


class ParsePrintOutput(unittest.TestCase):
    def test_happy_path(self):
        meta = prefetch.parse_print_output(f"Big Buck Bunny{US}aqz-KE-bpKQ{US}Youtube\n")
        self.assertEqual(meta, {"title": "Big Buck Bunny", "id": "aqz-KE-bpKQ", "site": "youtube"})

    def test_extractor_key_is_lowercased(self):
        meta = prefetch.parse_print_output(f"clip{US}123{US}TikTok")
        self.assertEqual(meta["site"], "tiktok")

    def test_na_values_become_empty(self):
        meta = prefetch.parse_print_output(f"NA{US}NA{US}Twitter")
        self.assertEqual(meta["title"], "")
        self.assertEqual(meta["id"], "")
        self.assertEqual(meta["site"], "twitter")

    def test_takes_last_marker_line_and_survives_noise(self):
        text = f"WARNING: something\nold{US}1{US}Reddit\nnew{US}2{US}Reddit\n"
        meta = prefetch.parse_print_output(text)
        self.assertEqual(meta["id"], "2")

    def test_garbage_returns_none(self):
        self.assertIsNone(prefetch.parse_print_output("no separators here"))
        self.assertIsNone(prefetch.parse_print_output(""))

    def test_title_with_separator_like_pipes_is_kept(self):
        meta = prefetch.parse_print_output(f"A | B: C{US}xyz{US}Vimeo")
        self.assertEqual(meta["title"], "A | B: C")

    def test_long_id_is_capped(self):
        meta = prefetch.parse_print_output(f"t{US}{'x' * 60}{US}Reddit")
        self.assertEqual(len(meta["id"]), 32)


class SiteFromUrl(unittest.TestCase):
    def test_known_hosts(self):
        cases = {
            "https://x.com/user/status/123": "twitter",
            "https://twitter.com/user/status/123": "twitter",
            "https://www.youtube.com/watch?v=abc": "youtube",
            "https://youtu.be/abc": "youtube",
            "https://www.reddit.com/r/videos/comments/abc/title/": "reddit",
            "https://old.reddit.com/r/videos/comments/abc/": "reddit",
            "https://v.redd.it/xyz": "reddit",
            "https://www.tiktok.com/@user/video/123": "tiktok",
            "https://vm.tiktok.com/ZM123/": "tiktok",
            "https://www.instagram.com/reel/abc/": "instagram",
        }
        for url, site in cases.items():
            self.assertEqual(prefetch.site_from_url(url), site, url)

    def test_unknown_host_uses_second_level_domain(self):
        self.assertEqual(prefetch.site_from_url("https://clips.twitch.tv/x"), "twitch")
        self.assertEqual(prefetch.site_from_url("https://vimeo.com/123"), "vimeo")

    def test_junk_urls_fall_back(self):
        self.assertEqual(prefetch.site_from_url("not a url"), "site")
        self.assertEqual(prefetch.site_from_url(""), "site")


class HintForError(unittest.TestCase):
    def test_login_errors_get_cookie_hint(self):
        for text in (
            "ERROR: [twitter] NSFW tweet requires authentication",
            "ERROR: Sign in to confirm you're not a bot",
            "ERROR: [instagram] login required",
            "ERROR: This video is only available for registered users. Use --cookies",
        ):
            hint = prefetch.hint_for_error(text)
            self.assertIn("cookies", hint.lower(), text)

    def test_ordinary_errors_get_no_hint(self):
        self.assertEqual(prefetch.hint_for_error("ERROR: Video unavailable"), "")
        self.assertEqual(prefetch.hint_for_error(""), "")


def make_stub(tc, body):
    """Write an executable fake yt-dlp script; auto-removed after the test."""
    fd, path = tempfile.mkstemp(prefix="fake-ytdlp-", suffix=".py")
    os.write(fd, f"#!{sys.executable}\n{body}".encode())
    os.close(fd)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    tc.addCleanup(os.unlink, path)
    return path


class FetchMetadata(unittest.TestCase):
    def _stub(self, body):
        return make_stub(self, body)

    def test_success(self):
        stub = self._stub(f'print("My Clip{US}id42{US}Twitter")\n')
        meta = prefetch.fetch_metadata(stub, "https://x.com/u/status/1", timeout=10)
        self.assertEqual(meta, {"title": "My Clip", "id": "id42", "site": "twitter"})

    def test_failure_returns_none(self):
        stub = self._stub('import sys; sys.exit(1)\n')
        self.assertIsNone(prefetch.fetch_metadata(stub, "https://x.com/u", timeout=10))

    def test_timeout_returns_none(self):
        stub = self._stub('import time; time.sleep(5)\n')
        self.assertIsNone(prefetch.fetch_metadata(stub, "https://x.com/u", timeout=0.5))

    def test_missing_binary_returns_none(self):
        self.assertIsNone(prefetch.fetch_metadata("/nonexistent/yt-dlp", "https://x.com/u", timeout=5))

    def test_cookies_flag_is_passed(self):
        stub = self._stub(
            "import sys\n"
            "assert '--cookies-from-browser' in sys.argv, sys.argv\n"
            f'print("t{US}i{US}Reddit")\n'
        )
        meta = prefetch.fetch_metadata(stub, "https://reddit.com/x", cookies_browser="chrome", timeout=10)
        self.assertIsNotNone(meta)


class RunnerMetadataIntegration(unittest.TestCase):
    def _runner_and_job(self, **job_kwargs):
        from footagegrab.jobs import Job
        from footagegrab.runner import DownloadRunner
        return DownloadRunner(dict), Job(**job_kwargs)

    def test_prefetch_fills_missing_title_id_site(self):
        stub = make_stub(self, f'print("Neat Clip{US}abc123{US}Twitter")\n')
        runner, job = self._runner_and_job(url="https://x.com/u/status/9", site="twitter")
        stages = []
        runner._ensure_metadata(job, {"cookies_browser": "none"}, stub,
                                lambda frac, stage: stages.append(stage))
        self.assertEqual(job.title, "Neat Clip")
        self.assertEqual(job.video_id, "abc123")
        self.assertEqual(job.site, "twitter")
        self.assertIn("fetching info", stages)

    def test_prefetch_skipped_when_metadata_present(self):
        stub = make_stub(self, 'import sys; sys.exit(1)  # would fail if called\n')
        runner, job = self._runner_and_job(
            url="https://youtube.com/watch?v=x", title="Known", video_id="x", site="youtube")
        runner._ensure_metadata(job, {}, stub, None)
        self.assertEqual(job.title, "Known")

    def test_prefetch_failure_leaves_job_usable(self):
        stub = make_stub(self, 'import sys; sys.exit(1)\n')
        runner, job = self._runner_and_job(url="https://x.com/u/status/9", site="twitter")
        runner._ensure_metadata(job, {}, stub, None)
        self.assertEqual(job.title, "")

    def test_plan_path_uses_site_date_fallback_naming(self):
        import time as _time
        runner, job = self._runner_and_job(url="https://x.com/u/status/9", site="twitter")
        with tempfile.TemporaryDirectory() as td:
            cfg = {"template_full": "{title}_{site}_{id}"}
            path = runner._plan_path(job, cfg, Path(td), "max")
        date = _time.strftime("%Y-%m-%d")
        self.assertEqual(path.name, f"twitter_{date}_twitter.mp4")

    def test_plan_path_site_token_with_real_metadata(self):
        runner, job = self._runner_and_job(
            url="https://www.reddit.com/r/videos/comments/a/b/",
            title="Great Post", video_id="a1b2", site="reddit")
        with tempfile.TemporaryDirectory() as td:
            cfg = {"template_full": "{title}_{site}_{id}"}
            path = runner._plan_path(job, cfg, Path(td), "max")
        self.assertEqual(path.name, "Great Post_reddit_a1b2.mp4")


if __name__ == "__main__":
    unittest.main()
