"""Dispatch messages from the extension to config, queue, and system helpers."""

import json
import logging

from . import config, system, timefmt
from .jobs import Job, RUNNING

log = logging.getLogger("footagegrab.router")

HISTORY_LIMIT = 40


class AppError(Exception):
    """Validation error whose message is safe to show in the UI."""


class Router:
    def __init__(self, queue, runner):
        self._queue = queue
        self._runner = runner
        self._handlers = {
            "ping": self._ping,
            "get_config": self._get_config,
            "set_config": self._set_config,
            "choose_folder": self._choose_folder,
            "enqueue": self._enqueue,
            "jobs": self._jobs,
            "cancel": self._cancel,
            "retry": self._retry,
            "reveal": self._reveal,
            "open_folder": self._open_folder,
            "update_ytdlp": self._update_ytdlp,
            "get_history": self._get_history,
        }

    def handle(self, msg):
        """Returns a reply dict (with 're' echoing the request id), never raises."""
        mid = msg.get("id")
        mtype = msg.get("type")
        handler = self._handlers.get(mtype)
        if handler is None:
            return {"re": mid, "ok": False, "error": f"unknown message type: {mtype}"}
        try:
            result = handler(msg) or {}
            return {"re": mid, "ok": True, **result}
        except AppError as exc:
            return {"re": mid, "ok": False, "error": str(exc)}
        except Exception as exc:
            log.exception("handler %s crashed", mtype)
            return {"re": mid, "ok": False, "error": f"host error: {exc}"}

    # -- handlers -----------------------------------------------------------

    def _ping(self, msg):
        from . import __version__
        cfg = config.load()
        return {"host_version": __version__, "health": system.health(cfg), "config": cfg}

    def _get_config(self, msg):
        return {"config": config.load()}

    def _set_config(self, msg):
        cfg, errors = config.update(msg.get("patch") or {})
        return {"config": cfg, "errors": errors}

    def _choose_folder(self, msg):
        path, error = system.choose_folder()
        if path is None:
            raise AppError(error if error != "canceled" else "canceled")
        cfg, errors = config.update({"output_dir": path})
        return {"config": cfg, "errors": errors, "path": path}

    def _enqueue(self, msg):
        url = str(msg.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise AppError("missing or invalid video URL")
        common = {
            "url": url,
            "video_id": str(msg.get("video_id") or "")[:32],
            "title": str(msg.get("title") or "")[:300],
        }
        mode = msg.get("mode") or ("segments" if msg.get("segments") else "full")
        jobs = []
        if mode == "full":
            jobs.append(Job(mode="full", **common))
        elif mode == "segments":
            raw = msg.get("segments") or []
            if not raw:
                raise AppError("no segments to grab — set In and Out first")
            group = None
            for seg in raw:
                try:
                    start = timefmt.parse_time(seg.get("start"))
                    end = timefmt.parse_time(seg.get("end"))
                except (ValueError, AttributeError):
                    raise AppError("segment has an unreadable time") from None
                if end - start < 0.2:
                    raise AppError(
                        f"segment {timefmt.fmt_clock(start)}–{timefmt.fmt_clock(end)}"
                        " is invalid — Out must be after In"
                    )
                job = Job(mode="segment", start=start, end=end, group=group, **common)
                group = group or job.id
                jobs.append(job)
        else:
            raise AppError(f"unknown mode: {mode}")
        for job in jobs:
            self._queue.submit(job)
        return {"jobs": [j.to_dict() for j in jobs]}

    def _jobs(self, msg):
        return {"jobs": self._queue.snapshot()}

    def _cancel(self, msg):
        job = self._queue.cancel(str(msg.get("job_id") or ""))
        if job is None:
            raise AppError("unknown job")
        if job.state == RUNNING:
            self._runner.cancel(job.id)
        return {"job": job.to_dict()}

    def _retry(self, msg):
        job = self._queue.retry(str(msg.get("job_id") or ""))
        if job is None:
            raise AppError("job is not retryable")
        return {"job": job.to_dict()}

    def _reveal(self, msg):
        ok, error = system.reveal(msg.get("path") or "")
        if not ok:
            raise AppError(error)
        return {}

    def _open_folder(self, msg):
        cfg = config.load()
        path = msg.get("path") or cfg.get("output_dir")
        ok, error = system.open_folder(path)
        if not ok:
            raise AppError(error)
        return {}

    def _update_ytdlp(self, msg):
        return system.update_ytdlp(config.load())

    def _get_history(self, msg):
        limit = int(msg.get("limit") or HISTORY_LIMIT)
        entries = []
        try:
            with open(config.history_path(), "r", encoding="utf-8") as f:
                lines = f.readlines()[-max(limit, 1):]
            for line in lines:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
        entries.reverse()  # newest first
        return {"history": entries}
