#!/usr/bin/env python3
"""FootageGrab native messaging host entry point.

Chrome launches this process when the extension connects, speaks framed JSON
over stdio, and closes stdin on disconnect. Downloads run on worker threads;
after stdin EOF we keep the process alive until in-flight jobs finish (Chrome
usually grants this, but a full browser quit can still kill us mid-download —
yt-dlp's .part files mean no corrupt finals either way).
"""

import json
import logging
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from footagegrab import __version__, config  # noqa: E402
from footagegrab.jobs import TERMINAL, JobQueue  # noqa: E402
from footagegrab.nm import NativeMessagingIO  # noqa: E402
from footagegrab.router import Router  # noqa: E402
from footagegrab.runner import DownloadRunner  # noqa: E402

DRAIN_TIMEOUT = 3600  # seconds to let in-flight jobs finish after disconnect
PROGRESS_PUSH_INTERVAL = 0.5


def setup_logging():
    handler = RotatingFileHandler(
        config.logs_dir() / "host.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main():
    config.augment_path()
    setup_logging()
    log = logging.getLogger("footagegrab.host")
    log.info("host starting, version %s", __version__)

    io = NativeMessagingIO()
    runner = DownloadRunner(config.load)
    recorded = set()  # job ids already appended to history
    last_push = {}  # job id -> monotonic time of last progress push

    def push_update(job):
        if job.state in TERMINAL and job.id not in recorded:
            recorded.add(job.id)
            try:
                with open(config.history_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps(job.to_dict(), ensure_ascii=False) + "\n")
            except OSError:
                log.warning("could not append history for %s", job.id)
        try:
            io.write({"type": "job_update", "job": job.to_dict()})
        except OSError:
            pass  # browser is gone; keep downloading

    def on_progress(job, fraction, stage):
        if fraction is not None:
            job.progress = fraction
        job.stage = stage
        now = time.monotonic()
        if now - last_push.get(job.id, 0.0) >= PROGRESS_PUSH_INTERVAL:
            last_push[job.id] = now
            push_update(job)

    def worker(job):
        return runner.run(job, on_progress=lambda f, s: on_progress(job, f, s))

    cfg = config.load()
    queue = JobQueue(worker, on_update=push_update, concurrency=cfg.get("max_concurrent", 2))
    queue.start()
    router = Router(queue, runner)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    io.write({"type": "hello", "host_version": __version__})

    while not stop.is_set():
        msg = io.read()
        if msg is None:
            break
        if not isinstance(msg, dict):
            continue
        reply = router.handle(msg)
        try:
            io.write(reply)
        except OSError:
            break

    active = queue.active_count()
    if active:
        log.info("stdin closed with %d active job(s); draining", active)
        queue.drain(DRAIN_TIMEOUT)
    queue.stop()
    log.info("host exiting")


if __name__ == "__main__":
    main()
