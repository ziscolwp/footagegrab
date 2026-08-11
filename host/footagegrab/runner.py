"""Run yt-dlp for a job, stream progress, and clean up after failures."""

import collections
import logging
import re
import subprocess
import threading
import time
from pathlib import Path

from . import config, naming, sections, timefmt

log = logging.getLogger("footagegrab.runner")

_PROGRESS_RE = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%")
_PROCESSING_PREFIXES = ("[Merger]", "[Fixup", "[VideoRemuxer", "[VideoConvertor")
_FINAL_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4a"}


class DownloadRunner:
    """Owns the yt-dlp subprocesses so running jobs can be canceled."""

    def __init__(self, get_config=config.load):
        self._get_config = get_config
        self._procs = {}
        self._lock = threading.Lock()

    def run(self, job, on_progress=None):
        """Blocking download for one job. Returns (ok, error, final_path)."""
        cfg = self._get_config()
        ytdlp = config.resolve_tool("yt-dlp", cfg.get("ytdlp_path"))
        if not ytdlp:
            return False, "yt-dlp not found. Install it with: brew install yt-dlp", ""
        ffmpeg = config.resolve_tool("ffmpeg", cfg.get("ffmpeg_path"))
        if not ffmpeg:
            return False, "ffmpeg not found. Install it with: brew install ffmpeg", ""
        try:
            out_dir = config.ensure_output_dir(cfg)
        except OSError as exc:
            return False, f"output folder unavailable: {exc}", ""

        quality = job.quality or cfg.get("quality", "best")
        accurate = cfg.get("accurate_cut", False) if job.accurate is None else job.accurate
        path = self._plan_path(job, cfg, out_dir, quality)
        try:
            argv = sections.build_download_args(
                url=job.url, out_path=path, quality=quality,
                mode=job.mode, start=job.start, end=job.end, accurate=accurate,
                cookies_browser=cfg.get("cookies_browser"),
                ytdlp_path=ytdlp, ffmpeg_path=ffmpeg,
            )
        except ValueError as exc:
            return False, str(exc), ""

        log.info("job %s argv: %s", job.id, " ".join(argv))
        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, errors="replace",
            )
        except OSError as exc:
            return False, f"could not start yt-dlp: {exc}", ""

        self._register(job.id, proc)
        stderr_tail = collections.deque(maxlen=25)
        pump = threading.Thread(target=self._pump_stderr, args=(proc, stderr_tail), daemon=True)
        pump.start()
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line or on_progress is None:
                    continue
                m = _PROGRESS_RE.search(line)
                if m:
                    on_progress(min(float(m.group(1)) / 100.0, 1.0), "downloading")
                elif line.startswith(_PROCESSING_PREFIXES):
                    on_progress(None, "processing")
            rc = proc.wait()
        finally:
            self._unregister(job.id)
            pump.join(timeout=2)

        if job.cancel_requested:
            self._cleanup_partials(path)
            return False, "canceled", ""
        if rc == 0:
            final = path if path.exists() else self._find_output(path)
            if final:
                log.info("job %s done: %s", job.id, final)
                return True, "", str(final)
            return False, "yt-dlp finished but produced no output file", ""
        self._cleanup_partials(path)
        error = self._summarize_error(stderr_tail, rc)
        log.warning("job %s failed rc=%s: %s", job.id, rc, error)
        return False, error, ""

    def cancel(self, job_id):
        """Terminate the subprocess for a running job, escalating to SIGKILL."""
        with self._lock:
            proc = self._procs.get(job_id)
        if proc is None:
            return False
        proc.terminate()
        timer = threading.Timer(5.0, lambda: proc.poll() is None and proc.kill())
        timer.daemon = True
        timer.start()
        return True

    def _plan_path(self, job, cfg, out_dir, quality):
        fields = {
            "title": naming.slugify(job.title or job.video_id or "clip"),
            "id": job.video_id or "video",
            "date": time.strftime("%Y-%m-%d"),
            "quality": quality,
        }
        if job.mode == "segment":
            fields["start"] = timefmt.fmt_file(job.start)
            fields["end"] = timefmt.fmt_file(job.end)
            template = cfg.get("template_segment", config.DEFAULTS["template_segment"])
        else:
            template = cfg.get("template_full", config.DEFAULTS["template_full"])
        stem = naming.render_template(template, fields)
        return naming.unique_path(out_dir, stem, ".mp4")

    def _register(self, job_id, proc):
        with self._lock:
            self._procs[job_id] = proc

    def _unregister(self, job_id):
        with self._lock:
            self._procs.pop(job_id, None)

    @staticmethod
    def _pump_stderr(proc, tail):
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                tail.append(line)

    @staticmethod
    def _summarize_error(tail, rc):
        lines = list(tail)
        errors = [l for l in lines if "ERROR" in l]
        picked = errors[-2:] if errors else lines[-3:]
        text = " | ".join(picked).strip()
        return text[:400] if text else f"yt-dlp exited with code {rc}"

    @staticmethod
    def _find_output(path):
        """yt-dlp occasionally lands on a sibling extension; find the real file."""
        stem = path.stem
        candidates = [
            p for p in path.parent.glob(f"{stem}.*")
            if p.suffix.lower() in _FINAL_EXTS and ".part" not in p.name
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_size)

    @staticmethod
    def _cleanup_partials(path):
        try:
            for p in path.parent.glob(f"{path.stem}*"):
                if ".part" in p.name or ".ytdl" in p.name or p.suffix == ".temp":
                    p.unlink(missing_ok=True)
        except OSError:
            pass
