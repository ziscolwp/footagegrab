import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class CounterTests(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        os.environ["FOOTAGEGRAB_HOME"] = self._home.name
        self.addCleanup(self._home.cleanup)
        self.addCleanup(os.environ.pop, "FOOTAGEGRAB_HOME", None)

    def test_sequential_per_key(self):
        from footagegrab import counters
        self.assertEqual(counters.next_index("vidA"), 1)
        self.assertEqual(counters.next_index("vidA"), 2)
        self.assertEqual(counters.next_index("vidB"), 1)
        self.assertEqual(counters.next_index("vidA"), 3)

    def test_persists_across_reads(self):
        from footagegrab import counters
        counters.next_index("vidA")
        counters.next_index("vidA")
        # a fresh read of the file continues the sequence
        self.assertEqual(counters.next_index("vidA"), 3)
        self.assertTrue((Path(self._home.name) / "counters.json").exists())

    def test_thread_safe(self):
        from footagegrab import counters
        got = []
        def worker():
            for _ in range(25):
                got.append(counters.next_index("vidX"))
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sorted(got), list(range(1, 101)))

    def test_corrupt_file_restarts_cleanly(self):
        from footagegrab import counters
        counters.counters_path().write_text("{not json", "utf-8")
        self.assertEqual(counters.next_index("vidA"), 1)


class EnqueueNumbering(unittest.TestCase):
    """Router assigns {n} in submission order so part 1/2/3 match the marks."""

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        os.environ["FOOTAGEGRAB_HOME"] = self._home.name
        self.addCleanup(self._home.cleanup)
        self.addCleanup(os.environ.pop, "FOOTAGEGRAB_HOME", None)
        from footagegrab import config
        config.add_destination(str(Path(self._home.name) / "out"))

    def _router(self):
        from footagegrab.router import Router

        class FakeQueue:
            def __init__(self):
                self.jobs = []
            def submit(self, job):
                self.jobs.append(job)
                return job

        q = FakeQueue()
        return Router(q, runner=None), q

    def test_segments_get_consecutive_numbers(self):
        router, q = self._router()
        reply = router.handle({"id": 1, "type": "enqueue",
                               "url": "https://www.youtube.com/watch?v=abc",
                               "video_id": "abc", "title": "T",
                               "segments": [{"start": 1, "end": 2},
                                            {"start": 5, "end": 8},
                                            {"start": 9, "end": 12}]})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual([j.n for j in q.jobs], [1, 2, 3])

    def test_numbering_continues_on_regrab_of_same_video(self):
        router, q = self._router()
        for _ in range(2):
            router.handle({"id": 1, "type": "enqueue",
                           "url": "https://www.youtube.com/watch?v=abc",
                           "video_id": "abc", "title": "T",
                           "segments": [{"start": 1, "end": 2}]})
        self.assertEqual([j.n for j in q.jobs], [1, 2])

    def test_different_videos_count_independently(self):
        router, q = self._router()
        for vid in ("abc", "xyz"):
            router.handle({"id": 1, "type": "enqueue",
                           "url": f"https://www.youtube.com/watch?v={vid}",
                           "video_id": vid, "title": "T", "mode": "full"})
        self.assertEqual([j.n for j in q.jobs], [1, 1])

    def test_url_keys_numbering_when_no_video_id(self):
        router, q = self._router()
        for _ in range(2):
            router.handle({"id": 1, "type": "enqueue", "mode": "full",
                           "url": "https://x.com/u/status/9", "source": "context_menu"})
        self.assertEqual([j.n for j in q.jobs], [1, 2])

    def test_no_counter_consumed_when_template_lacks_n(self):
        from footagegrab import config, counters
        config.update({"template_full": "{title}", "template_segment": "{title}"})
        router, q = self._router()
        router.handle({"id": 1, "type": "enqueue", "mode": "full",
                       "url": "https://www.youtube.com/watch?v=abc", "video_id": "abc"})
        self.assertIsNone(q.jobs[0].n)
        self.assertEqual(counters.next_index("abc"), 1)  # untouched

    def test_custom_name_is_accepted_and_capped(self):
        router, q = self._router()
        router.handle({"id": 1, "type": "enqueue", "mode": "full",
                       "url": "https://www.youtube.com/watch?v=abc", "video_id": "abc",
                       "custom_name": "  Hero shot  " + "x" * 200})
        self.assertTrue(q.jobs[0].custom_name.startswith("Hero shot"))
        self.assertLessEqual(len(q.jobs[0].custom_name), 80)


class PlanPathNaming(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        os.environ["FOOTAGEGRAB_HOME"] = self._home.name
        self.addCleanup(self._home.cleanup)
        self.addCleanup(os.environ.pop, "FOOTAGEGRAB_HOME", None)

    def _plan(self, job, template):
        from footagegrab.runner import DownloadRunner
        runner = DownloadRunner(dict)
        with tempfile.TemporaryDirectory() as td:
            cfg = {"template_segment": template, "template_full": template}
            return runner._plan_path(job, cfg, Path(td), "max").name

    def test_clean_numbered_name(self):
        from footagegrab.jobs import Job
        job = Job(url="u", video_id="abc", title="Oprah: The Interview",
                  mode="segment", start=1, end=2)
        job.n = 2
        self.assertEqual(self._plan(job, "{title} {n}"), "Oprah The Interview 2.mp4")

    def test_custom_name_beats_video_title(self):
        from footagegrab.jobs import Job
        job = Job(url="u", video_id="abc", title="Some Long Video Title",
                  mode="full", custom_name="Hero shot")
        job.n = 1
        self.assertEqual(self._plan(job, "{title} {n}"), "Hero shot 1.mp4")


if __name__ == "__main__":
    unittest.main()
