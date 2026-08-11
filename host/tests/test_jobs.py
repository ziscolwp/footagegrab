import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab.jobs import (CANCELED, DONE, FAILED, QUEUED, RUNNING,
                              InvalidTransition, Job, JobQueue)


def make_job(**kw):
    defaults = dict(url="https://youtube.com/watch?v=x", video_id="x", title="t",
                    mode="segment", start=1.0, end=5.0)
    defaults.update(kw)
    return Job(**defaults)


class StateMachineTests(unittest.TestCase):
    def test_happy_path(self):
        job = make_job()
        self.assertEqual(job.state, QUEUED)
        job.transition(RUNNING)
        job.transition(DONE)
        self.assertIsNotNone(job.finished)

    def test_illegal_transitions_raise(self):
        job = make_job()
        with self.assertRaises(InvalidTransition):
            job.transition(DONE)  # queued -> done skips running
        job.transition(RUNNING)
        job.transition(FAILED)
        with self.assertRaises(InvalidTransition):
            job.transition(RUNNING)  # terminal states are final

    def test_retry_clone_keeps_group_bumps_attempts(self):
        job = make_job()
        clone = job.clone_for_retry()
        self.assertNotEqual(clone.id, job.id)
        self.assertEqual(clone.group, job.group)
        self.assertEqual(clone.attempts, 2)
        self.assertEqual(clone.state, QUEUED)


class QueueTests(unittest.TestCase):
    def _drained_queue(self, worker, jobs, concurrency=2):
        updates = []
        q = JobQueue(worker, on_update=lambda j: updates.append((j.id, j.state)), concurrency=concurrency)
        q.start()
        for job in jobs:
            q.submit(job)
        self.assertTrue(q.drain(timeout=10), "queue did not drain")
        q.stop()
        return q, updates

    def test_success_and_failure_are_independent(self):
        def worker(job):
            if job.title == "bad":
                return False, "boom", ""
            return True, "", f"/tmp/{job.id}.mp4"

        good, bad = make_job(title="good"), make_job(title="bad")
        q, _ = self._drained_queue(worker, [good, bad])
        self.assertEqual(good.state, DONE)
        self.assertTrue(good.file.endswith(".mp4"))
        self.assertEqual(bad.state, FAILED)
        self.assertEqual(bad.error, "boom")

    def test_worker_exception_fails_job_not_thread(self):
        def worker(job):
            raise RuntimeError("kaput")

        job = make_job()
        self._drained_queue(worker, [job])
        self.assertEqual(job.state, FAILED)
        self.assertIn("kaput", job.error)

    def test_cancel_queued_job_never_runs(self):
        ran = []
        gate = threading.Event()

        def worker(job):
            if job.title == "blocker":
                gate.wait(5)
            ran.append(job.id)
            return True, "", "/tmp/x.mp4"

        blocker = make_job(title="blocker")
        victim = make_job(title="victim")
        q = JobQueue(worker, concurrency=1)
        q.start()
        q.submit(blocker)
        q.submit(victim)
        q.cancel(victim.id)
        gate.set()
        self.assertTrue(q.drain(timeout=10))
        q.stop()
        self.assertEqual(victim.state, CANCELED)
        self.assertNotIn(victim.id, ran)

    def test_cancel_running_job_marks_canceled(self):
        started = threading.Event()
        release = threading.Event()

        def worker(job):
            started.set()
            release.wait(5)
            return False, "interrupted", ""

        job = make_job()
        q = JobQueue(worker, concurrency=1)
        q.start()
        q.submit(job)
        self.assertTrue(started.wait(5))
        q.cancel(job.id)  # sets cancel_requested; worker outcome is overridden
        release.set()
        self.assertTrue(q.drain(timeout=10))
        q.stop()
        self.assertEqual(job.state, CANCELED)

    def test_retry_requeues_failed_job(self):
        attempts = []

        def worker(job):
            attempts.append(job.attempts)
            return (False, "flaky", "") if job.attempts == 1 else (True, "", "/tmp/ok.mp4")

        job = make_job()
        q = JobQueue(worker, concurrency=1)
        q.start()
        q.submit(job)
        self.assertTrue(q.drain(timeout=10))
        clone = q.retry(job.id)
        self.assertIsNotNone(clone)
        self.assertTrue(q.drain(timeout=10))
        q.stop()
        self.assertEqual(attempts, [1, 2])
        self.assertEqual(clone.state, DONE)
        self.assertIsNone(q.retry(clone.id), "done jobs are not retryable")


if __name__ == "__main__":
    unittest.main()
