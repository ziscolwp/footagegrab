"""Dispatch messages from the extension to config, queue, and system helpers."""

import json
import logging
import os

from . import config, counters, prefetch, system, timefmt
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
            "add_destination": self._add_destination,
            "set_destination": self._set_destination,
            "remove_destination": self._remove_destination,
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

    def _add_destination(self, msg):
        path, error = system.choose_folder()
        if path is None:
            raise AppError(error if error != "canceled" else "canceled")
        cfg, entry = config.add_destination(path, label=msg.get("label") or "")
        return {"config": cfg, "destination": entry}

    def _set_destination(self, msg):
        cfg, error = config.select_destination(str(msg.get("dest_id") or ""))
        if error:
            raise AppError(error)
        return {"config": cfg}

    def _remove_destination(self, msg):
        cfg, error = config.remove_destination(str(msg.get("dest_id") or ""))
        if error:
            raise AppError(error)
        return {"config": cfg}

    def _enqueue(self, msg):
        url = str(msg.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise AppError("missing or invalid video URL")
        cfg_now = config.load()
        override = str(msg.get("destination_id") or "")[:16]
        if override:
            # config.selected_destination falls back to the first entry when
            # its id doesn't match anything — correct for the config's own
            # destination_id, but a per-job override that names no real
            # destination must fail loudly instead of silently landing in
            # destination #1.
            if not any(d["id"] == override for d in config.destinations(cfg_now)):
                raise AppError(f"unknown destination: {override}")
            cfg_now = dict(cfg_now, destination_id=override)
        if not config.selected_destination(cfg_now):
            raise AppError("no destination set — add a folder in the extension first")
        try:
            config.validate_output_dir(cfg_now)
        except OSError as exc:
            raise AppError(f"destination unavailable: {exc}") from None
        common = {
            "url": url,
            "video_id": str(msg.get("video_id") or "")[:32],
            "title": str(msg.get("title") or "")[:300],
            "site": prefetch.site_from_url(url),
            "source": str(msg.get("source") or "player")[:24],
            "custom_name": str(msg.get("custom_name") or "").strip()[:80],
            "destination_id": override,
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
        # {n} is assigned here, in submission order, so part numbers always
        # match the order the user marked/grabbed — worker scheduling can't
        # reshuffle them. Counter key: video id, or the URL before prefetch.
        cfg = config.load()
        template = cfg.get("template_full") if mode == "full" else cfg.get("template_segment")
        if "{n}" in str(template or ""):
            key = common["video_id"] or url
            for job in jobs:
                job.n = counters.next_index(key)
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
        # effective folder, not raw output_dir — the extension's selected
        # destination is the source of truth, so "Open folder" must resolve
        # it the same way the download path does, not open something stale
        path = msg.get("path") or os.path.expanduser(config.effective_output_dir(cfg))
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
