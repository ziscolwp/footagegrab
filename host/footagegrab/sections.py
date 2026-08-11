"""Build yt-dlp argv for full and segment downloads.

Pure functions so the exact command line is unit-testable. Premiere compatibility
drives format selection: prefer H.264 + AAC in an mp4 container over higher-res
VP9/AV1 that Premiere cannot read without plugins.
"""

from .timefmt import fmt_section

# -S format sort strings, keyed by the quality setting exposed in the UI.
QUALITY_SORT = {
    "best": "vcodec:h264,res,acodec:m4a",
    "1080": "vcodec:h264,res:1080,acodec:m4a",
    "720": "vcodec:h264,res:720,acodec:m4a",
}

VALID_COOKIE_BROWSERS = ("chrome", "brave", "chromium", "edge")


def section_spec(start, end):
    return f"*{fmt_section(start)}-{fmt_section(end)}"


def build_download_args(
    *,
    url,
    out_path,
    quality="best",
    mode="full",
    start=None,
    end=None,
    accurate=False,
    cookies_browser=None,
    ytdlp_path="yt-dlp",
    ffmpeg_path=None,
):
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
