"""Build yt-dlp argv for full and segment downloads.

Pure functions so the exact command line is unit-testable. Premiere compatibility
drives format selection: prefer H.264 + AAC in an mp4 container over higher-res
VP9/AV1 that Premiere cannot read without plugins.
"""

from .timefmt import fmt_section

# -S format sort strings, keyed by the quality setting exposed in the UI.
# "max": highest resolution wins outright (4K+ arrives as VP9/AV1 — compat.py
# transcodes those to H.264 afterwards). Capped tiers prefer native H.264 so
# they need no conversion at all.
QUALITY_SORT = {
    "max": "res,vcodec:h264,acodec:m4a",
    "1080": "vcodec:h264,res:1080,acodec:m4a",
    "720": "vcodec:h264,res:720,acodec:m4a",
}

VALID_COOKIE_BROWSERS = ("chrome", "brave", "chromium", "edge")

# YouTube intermittently 403s the direct stream URLs that --download-sections
# hands to ffmpeg (ffmpeg then exits with code 8). These signatures mean "try
# again, the video itself is fine" — as opposed to login walls or removals.
_TRANSIENT_MARKERS = (
    "ffmpeg exited with code 8",
    "http error 403",
    "unable to continue",  # "fragment N not found, unable to continue"
    "got error:",
    "connection reset",
    "timed out",
)

# The full-download-then-cut fallback is only worth it when the whole video is
# reasonably small; past this many seconds a plain retry is used instead.
FALLBACK_MAX_DURATION = 1800


def is_transient_error(text):
    """True when a failed download looks retryable (flaky stream URLs, not a
    login wall / private / removed video)."""
    lowered = str(text or "").lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)


def plan_retry(failed_attempt, mode):
    """Ladder for transient failures. Returns the next attempt's strategy or
    None to give up. failed_attempt is 1-based (1 = the fast path just failed).

    Rung 2 rotates the YouTube player client so the retry takes a different
    URL-issuing path instead of re-rolling the same dice. Rung 3 asks the
    runner to consider the full-download-and-cut fallback (segments only —
    full downloads already use yt-dlp's resilient native downloader, so they
    just get one more plain retry)."""
    if failed_attempt == 1:
        return {"delay": 3, "client": "web_safari", "try_fallback": False}
    if failed_attempt == 2:
        return {"delay": 5, "client": None, "try_fallback": mode == "segment"}
    return None


def build_local_cut_args(ffmpeg_path, src, dst, start, end, accurate=False):
    """ffmpeg argv cutting [start, end) out of a local file. Stream-copy by
    default (fast, keyframe-snapped — same trade-off as remote section
    downloads); accurate re-encodes so the cut lands on the exact frame."""
    duration = float(end) - float(start)
    if duration <= 0:
        raise ValueError("segment end must be after start")
    argv = [
        str(ffmpeg_path), "-hide_banner", "-y",
        "-ss", fmt_section(start),
        "-i", str(src),
        "-t", fmt_section(duration),
    ]
    if accurate:
        argv += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac"]
    else:
        argv += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    argv.append(str(dst))
    return argv


def section_spec(start, end):
    return f"*{fmt_section(start)}-{fmt_section(end)}"


def build_download_args(
    *,
    url,
    out_path,
    quality="max",
    mode="full",
    start=None,
    end=None,
    accurate=False,
    cookies_browser=None,
    ytdlp_path="yt-dlp",
    ffmpeg_path=None,
    player_client=None,
):
    if quality == "best":  # legacy alias
        quality = "max"
    if quality not in QUALITY_SORT:
        raise ValueError(f"unknown quality: {quality!r}")
    if mode not in ("full", "segment"):
        raise ValueError(f"unknown mode: {mode!r}")
    if mode == "segment":
        if start is None or end is None:
            raise ValueError("segment mode needs start and end")
        if float(end) <= float(start):
            raise ValueError("segment end must be after start")

    argv = [
        str(ytdlp_path),
        "--no-playlist",
        "--newline",
        "--retries", "3",
        "-S", QUALITY_SORT[quality],
        "--merge-output-format", "mp4",
    ]
    if ffmpeg_path:
        argv += ["--ffmpeg-location", str(ffmpeg_path)]
    if player_client:
        argv += ["--extractor-args", f"youtube:player_client={player_client}"]
    if cookies_browser and cookies_browser != "none":
        if cookies_browser not in VALID_COOKIE_BROWSERS:
            raise ValueError(f"unknown cookies browser: {cookies_browser!r}")
        argv += ["--cookies-from-browser", cookies_browser]
    if mode == "segment":
        argv += ["--download-sections", section_spec(start, end)]
        if accurate:
            # Re-encodes around the cut so In/Out are trustworthy in the edit;
            # without it, cuts snap to the nearest keyframe (fast but loose).
            argv += ["--force-keyframes-at-cuts"]
    argv += ["-o", str(out_path), url]
    return argv
