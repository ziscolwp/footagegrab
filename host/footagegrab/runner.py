# TODO: split by concern
"""Run yt-dlp for a job, stream progress, and clean up after failures."""

import collections
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import compat, config, naming, prefetch, sections, timefmt

log = logging.getLogger("footagegrab.runner")

_PROGRESS_RE = re.compile(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%")
_PROCESSING_PREFIXES = ("[Merger]", "[Fixup", "[VideoRemuxer", "[VideoConvertor")
_FINAL_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4a"}
# Staging-only intermediates that share the job's stem and a "final" suffix,
# and must never be mistaken for the finished output by _find_output: the
# fallback's whole-video temp (<stem>.full.mp4) and the compat-transcode
# scratch file (<stem>.h264tmp.mp4).
_INTERMEDIATE_MARKERS = (".full.", ".h264tmp.")


def sweep_stage_dir(out_dir):
    """Remove a staging folder left by a crash. Safe when absent."""
    stage = Path(out_dir) / config.STAGE_DIR_NAME
    if not stage.is_dir():
        return
    try:
        shutil.rmtree(stage)
    except OSError:
        log.warning("could not sweep %s", stage, exc_info=True)


class DownloadRunner:
    """Owns the yt-dlp subprocesses so running jobs can be canceled."""

    def __init__(self, get_config=config.load, pot=None):
        self._get_config = get_config
        self._pot = pot  # PO-token sidecar supervisor; None disables it
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
        if getattr(job, "destination_id", ""):
            cfg = dict(cfg, destination_id=job.destination_id)
        try:
            out_dir = config.ensure_output_dir(cfg)
        except OSError as exc:
            return False, f"output folder unavailable: {exc}", ""
        try:
            stage_dir = config.ensure_stage_dir(out_dir)
        except OSError as exc:
            return False, f"staging folder unavailable: {exc}", ""

        quality = job.quality or cfg.get("quality", "max")
        accurate = cfg.get("accurate_cut", False) if job.accurate is None else job.accurate
        cookies = cfg.get("cookies_browser")
        self._ensure_metadata(job, cfg, ytdlp, on_progress)
        planned = self._plan_path(job, cfg, out_dir, quality)
        path = stage_dir / planned.name

        # Transient stream failures (YouTube 403s the URLs it just issued;
        # ffmpeg exits with code 8) climb a ladder: plain run -> delayed retry
        # on a rotated player client -> full-download-and-local-cut fallback.
        # Permanent errors (login walls, removed videos) exit on the first rung.
        attempt = 0
        client = None
        first_error = ""
        ok, error, final = False, "", ""
        while True:
            attempt += 1
            # Best-effort per attempt (retries re-extract, so a sidecar that
            # died mid-session gets restarted here). A live sidecar upgrades
            # mweb from progressive 360p to full adaptive streams; when it is
            # unavailable the grab proceeds tokenless — never fails.
            if self._pot is not None:
                try:
                    self._pot.ensure_running()
                except Exception:
                    log.warning("PO token supervisor failed — grabbing "
                                "tokenless", exc_info=True)
            try:
                argv = sections.build_download_args(
                    url=job.url, out_path=path, quality=quality,
                    mode=job.mode, start=job.start, end=job.end, accurate=accurate,
                    cookies_browser=cookies,
                    ytdlp_path=ytdlp, ffmpeg_path=ffmpeg, player_client=client,
                )
            except ValueError as exc:
                return False, str(exc), ""
            ok, error, final = self._attempt(job, argv, path, on_progress)
            if ok:
                break
            if job.cancel_requested or error == "canceled":
                return False, "canceled", ""
            first_error = first_error or error
            # A rotated player client can come back with no playable formats at
            # all (YouTube's SABR gating). That is a property of the client we
            # picked, not of the video — drop the override, keep climbing, and
            # report the original failure rather than the misleading one.
            if client and sections.is_format_unavailable_error(error):
                log.info("job %s: client %s served no formats — dropping override",
                         job.id, client)
                error = first_error
            elif not sections.is_transient_error(error):
                return False, error, ""
            plan = sections.plan_retry(attempt, job.mode)
            if plan is None:
                return False, error, ""
            log.info("job %s: transient failure on attempt %s — retrying in %ss%s",
                     job.id, attempt, plan["delay"],
                     f" via {plan['client']}" if plan["client"] else "")
            if on_progress:
                # 0.0 resets the stale bar from the failed attempt
                on_progress(0.0, "retrying")
            if not self._sleep_unless_canceled(job, plan["delay"]):
                return False, "canceled", ""
            if plan["try_fallback"]:
                duration = prefetch.fetch_duration(ytdlp, job.url, cookies_browser=cookies)
                # the probe isn't a registered subprocess, so a cancel pressed
                # while it ran must be honored here — before the big download
                if job.cancel_requested:
                    return False, "canceled", ""
                if duration is not None and duration <= sections.FALLBACK_MAX_DURATION:
                    ok, error, final = self._run_fallback(
                        job, ytdlp, ffmpeg, out_dir, path, quality, accurate,
                        cookies, on_progress,
                    )
                    if ok:
                        break
                    if job.cancel_requested or error == "canceled":
                        return False, "canceled", ""
                    if not sections.is_transient_error(error):
                        return False, error, ""
                    # a transiently-failed fallback is not the end: the rest
                    # of the client chain (android_vr, tv_downgraded) takes a
                    # different URL-issuing path and is still worth climbing
                    log.info("job %s: fallback failed transiently — "
                             "continuing the client ladder", job.id)
                # video too long (or length unknown) for the fallback — the
                # loop continues into the remaining client rungs instead
            client = plan["client"]

        if cfg.get("compat_transcode", True):
            final, cerr = self._ensure_compat(job, Path(final), ffmpeg, on_progress)
            if cerr == "canceled":
                Path(final).unlink(missing_ok=True)
                return False, "canceled", ""
        try:
            final = self._deliver(Path(final), out_dir)
        except OSError as exc:
            Path(final).unlink(missing_ok=True)
            return False, f"could not deliver to {out_dir}: {exc}", ""
        log.info("job %s done: %s", job.id, final)
        return True, "", str(final)

    def _attempt(self, job, argv, path, on_progress):
        """One yt-dlp run. Returns (ok, error, final_path)."""
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
                return True, "", str(final)
            return False, "yt-dlp finished but produced no output file", ""
        self._cleanup_partials(path)
        error = self._summarize_error(stderr_tail, rc)
        log.warning("job %s failed rc=%s: %s", job.id, rc, error)
        return False, error, ""

    def _run_fallback(self, job, ytdlp, ffmpeg, out_dir, path, quality,
                      accurate, cookies, on_progress):
        """Last rung for segments: download the whole video with yt-dlp's
        native downloader (which survives the 403s that kill ffmpeg's URL
        fetch), then cut the requested section locally. The temp file lives in
        a hidden subfolder the Premiere watcher never lists."""
        if job.cancel_requested:
            return False, "canceled", ""
        log.info("job %s: falling back to full download + local cut", job.id)
        try:
            tmp_dir = config.ensure_stage_dir(out_dir)
        except OSError as exc:
            return False, f"fallback temp folder unavailable: {exc}", ""
        tmp_path = tmp_dir / (path.stem + ".full.mp4")
        try:
            argv = sections.build_download_args(
                url=job.url, out_path=tmp_path, quality=quality, mode="full",
                cookies_browser=cookies, ytdlp_path=ytdlp, ffmpeg_path=ffmpeg,
            )
        except ValueError as exc:
            return False, str(exc), ""
        ok, error, full_path = self._attempt(job, argv, tmp_path, on_progress)
        if not ok:
            self._cleanup_fallback_tmp(tmp_path)
            return False, error, ""

        if on_progress:
            on_progress(None, "processing")
        cut_argv = sections.build_local_cut_args(
            ffmpeg, full_path, path, job.start, job.end, accurate=accurate,
        )
        try:
            proc = subprocess.Popen(
                cut_argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self._cleanup_fallback_tmp(tmp_path, full_path)
            return False, f"could not start ffmpeg: {exc}", ""
        self._register(job.id, proc)
        try:
            rc = proc.wait()
        finally:
            self._unregister(job.id)
        self._cleanup_fallback_tmp(tmp_path, full_path)
        if job.cancel_requested:
            Path(path).unlink(missing_ok=True)
            return False, "canceled", ""
        if rc == 0 and Path(path).exists():
            return True, "", str(path)
        Path(path).unlink(missing_ok=True)
        return False, "local section cut failed", ""

    @staticmethod
    def _cleanup_fallback_tmp(tmp_path, full_path=None):
        # The staging folder is shared with other jobs (see run()) — never
        # remove it here, only the files this fallback attempt created.
        for p in (tmp_path, full_path):
            if p:
                Path(p).unlink(missing_ok=True)

    @staticmethod
    def _sleep_unless_canceled(job, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if job.cancel_requested:
                return False
            time.sleep(0.2)
        return True

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

    def _ensure_compat(self, job, path, ffmpeg, on_progress):
        """Re-encode VP9/AV1 downloads to H.264 in place. Returns (path, error).

        Best-effort: if probing or every encoder fails, the original file is
        kept and the job still succeeds — a playable file beats a failed job.
        """
        ffprobe = compat.find_ffprobe(ffmpeg)
        info = compat.probe(ffprobe, path) if ffprobe else None
        if not info or info["vcodec"] in compat.SAFE_VCODECS:
            return path, ""
        log.info("job %s: %s is %s — transcoding to H.264",
                 job.id, path.name, info["vcodec"])
        if on_progress:
            on_progress(0.0, "transcoding")
        dst = path.with_name(path.stem + ".h264tmp.mp4")
        for encoder in compat.encoder_candidates():
            argv = compat.build_transcode_args(
                ffmpeg, path, dst,
                height=info["height"], acodec=info["acodec"], encoder=encoder,
            )
            try:
                proc = subprocess.Popen(
                    argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, errors="replace",
                )
            except OSError:
                break
            self._register(job.id, proc)
            try:
                for line in proc.stdout:
                    frac = compat.parse_progress_line(line.strip(), info["duration"])
                    if frac is not None and on_progress:
                        on_progress(frac, "transcoding")
                rc = proc.wait()
            finally:
                self._unregister(job.id)
            if job.cancel_requested:
                dst.unlink(missing_ok=True)
                return path, "canceled"
            if rc == 0 and dst.exists() and dst.stat().st_size > 0:
                path.unlink(missing_ok=True)
                dst.rename(path)
                return path, ""
            dst.unlink(missing_ok=True)
            log.warning("job %s: %s failed (rc=%s), trying next encoder",
                        job.id, encoder, rc)
        log.warning("job %s: transcode failed — keeping original %s file",
                    job.id, info["vcodec"])
        return path, ""

    def _ensure_metadata(self, job, cfg, ytdlp, on_progress):
        """Context-menu/adapter grabs arrive with only a URL — resolve title,
        id, and site via a quick simulate run. Failure is fine: naming falls
        back to site+date and the download proceeds regardless."""
        if job.title and job.video_id:
            return
        if on_progress:
            on_progress(None, "fetching info")
        meta = prefetch.fetch_metadata(
            ytdlp, job.url, cookies_browser=cfg.get("cookies_browser"),
        )
        if meta:
            job.title = job.title or meta["title"]
            job.video_id = job.video_id or meta["id"]
            job.site = meta["site"] or job.site

    def _plan_path(self, job, cfg, out_dir, quality):
        site = job.site or prefetch.site_from_url(job.url)
        date = time.strftime("%Y-%m-%d")
        fields = {
            "title": naming.slugify(job.custom_name or job.title or job.video_id
                                    or f"{site}_{date}"),
            "id": job.video_id or "",
            "site": site,
            "n": job.n if job.n is not None else "",
            "date": date,
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

    @staticmethod
    def _deliver(staged_path, out_dir):
        """Move a finished file out of staging. Returns its final path.

        os.replace is atomic within a volume, so the destination goes from
        "no such file" to "complete file" with nothing observable between —
        which is what keeps Dropbox and the Premiere watcher from ever seeing
        a partial clip. The unique name is resolved here, at delivery time,
        because post-processing can change the extension.
        """
        staged_path = Path(staged_path)
        final = naming.unique_path(out_dir, staged_path.stem, staged_path.suffix)
        os.replace(staged_path, final)
        return final

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
        if not text:
            return f"yt-dlp exited with code {rc}"
        hint = prefetch.hint_for_error(text)
        if hint:
            text = f"{text[:320]} — {hint}"
        return text[:400]

    @staticmethod
    def _find_output(path):
        """yt-dlp occasionally lands on a sibling extension; find the real file."""
        stem = path.stem
        # Markers are matched only against the part of the name after the
        # stem: _find_output(tmp_path) is itself called with stem "<clip>.full"
        # (the fallback's whole-video temp) or "<clip>.h264tmp" (the compat
        # scratch file), and those legitimate stems must not disqualify their
        # own sibling-extension candidates (e.g. "<clip>.full.mkv").
        candidates = [
            p for p in path.parent.glob(f"{stem}.*")
            if p.suffix.lower() in _FINAL_EXTS and ".part" not in p.name
            and not any(marker in p.name[len(stem):] for marker in _INTERMEDIATE_MARKERS)
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
