"""Job model, state machine, and threaded download queue.

States: queued -> running -> done | failed | canceled (queued can also cancel).
Sibling segments from one video are independent jobs sharing a group id, so one
failure never kills the rest.
"""

import itertools
import queue
import threading
import time

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELED = "canceled"

TERMINAL = frozenset({DONE, FAILED, CANCELED})
_ALLOWED = frozenset({
    (QUEUED, RUNNING),
    (QUEUED, CANCELED),
    (RUNNING, DONE),
    (RUNNING, FAILED),
    (RUNNING, CANCELED),
})

_seq = itertools.count(1)


class InvalidTransition(Exception):
    pass


class Job:
    def __init__(self, *, url, video_id="", title="", mode="full", start=None,
                 end=None, group=None, quality=None, accurate=None, attempts=1,
                 site="", source="player"):
        self.id = f"j{next(_seq)}-{int(time.time() * 1000) % 100000000}"
        self.group = group or self.id
        self.url = url
        self.video_id = video_id
        self.title = title
        self.site = site  # twitter | reddit | tiktok | youtube | ... ({site} token)
        self.source = source  # player | context_menu | adapter | toolbar
        self.mode = mode  # full | segment
        self.start = start
        self.end = end
        self.quality = quality  # None -> use config at run time
        self.accurate = accurate  # None -> use config at run time
        self.attempts = attempts
        self.state = QUEUED
        self.progress = 0.0
        self.stage = "queued"
        self.file = ""
        self.error = ""
        self.created = time.time()
        self.finished = None
        self.cancel_requested = False

    def transition(self, new_state):
        if (self.state, new_state) not in _ALLOWED:
            raise InvalidTransition(f"{self.state} -> {new_state}")
        self.state = new_state
        if new_state in TERMINAL:
            self.finished = time.time()

    def clone_for_retry(self):
        return Job(url=self.url, video_id=self.video_id, title=self.title,
                   mode=self.mode, start=self.start, end=self.end, group=self.group,
                   quality=self.quality, accurate=self.accurate,
                   attempts=self.attempts + 1, site=self.site, source=self.source)

    def to_dict(self):
        return {
            "id": self.id, "group": self.group, "url": self.url,
            "video_id": self.video_id, "title": self.title, "mode": self.mode,
            "site": self.site, "source": self.source,
            "start": self.start, "end": self.end, "state": self.state,
            "progress": round(self.progress, 3), "stage": self.stage,
            "file": self.file, "error": self.error, "attempts": self.attempts,
            "created": self.created, "finished": self.finished,
        }


class JobQueue:
    """Fixed pool of worker threads draining a FIFO of job ids."""

    def __init__(self, worker, on_update=None, concurrency=2):
        self._worker = worker  # callable(job) -> (ok, error, path)
        self._on_update = on_update or (lambda job: None)
        self._concurrency = max(1, int(concurrency))
        self._q = queue.Queue()
        self._jobs = {}
        self._lock = threading.Lock()
        self._threads = []

    def start(self):
        for i in range(self._concurrency):
            t = threading.Thread(target=self._loop, daemon=True, name=f"fg-worker-{i}")
            t.start()
            self._threads.append(t)

    def stop(self):
        for _ in self._threads:
            self._q.put(None)

    def submit(self, job):
        with self._lock:
            self._jobs[job.id] = job
        self._q.put(job.id)
        self._notify(job)
        return job

    def get(self, job_id):
        with self._lock:
            return self._jobs.get(job_id)

    def snapshot(self):
        with self._lock:
            jobs = list(self._jobs.values())
        return [j.to_dict() for j in sorted(jobs, key=lambda j: j.created)]

    def active_count(self):
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.state not in TERMINAL)

    def cancel(self, job_id):
        """Cancel a job. Returns the job, or None if unknown. The caller is
        responsible for killing the subprocess of a RUNNING job."""
        transitioned = False
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.state == QUEUED:
                job.transition(CANCELED)
                job.stage = "canceled"
                transitioned = True
            elif job.state == RUNNING:
                job.cancel_requested = True
        if transitioned:
            self._notify(job)
        return job

    def retry(self, job_id):
        """Re-queue a failed/canceled job as a fresh attempt. None if not retryable."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in (FAILED, CANCELED):
                return None
            clone = job.clone_for_retry()
        return self.submit(clone)

    def drain(self, timeout):
        """Wait for all jobs to reach a terminal state. True if drained."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.active_count() == 0:
                return True
            time.sleep(0.2)
        return self.active_count() == 0

    def _loop(self):
        while True:
            job_id = self._q.get()
            if job_id is None:
                return
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None or job.state != QUEUED:
                    continue
                job.transition(RUNNING)
                job.stage = "starting"
            self._notify(job)
            try:
                ok, error, path = self._worker(job)
            except Exception as exc:  # worker must never kill the thread
                ok, error, path = False, f"internal error: {exc}", ""
            with self._lock:
                if job.state == RUNNING:
                    if job.cancel_requested:
                        job.transition(CANCELED)
                        job.stage = "canceled"
                    elif ok:
                        job.transition(DONE)
                        job.file = path
                        job.progress = 1.0
                        job.stage = "done"
                    else:
                        job.transition(FAILED)
                        job.error = error or "unknown error"
                        job.stage = "failed"
            self._notify(job)

    def _notify(self, job):
        try:
            self._on_update(job)
        except Exception:
            pass
