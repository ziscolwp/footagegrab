"""Premiere compatibility: probe codecs, transcode non-H.264 downloads.

YouTube serves 4K+ only as VP9/AV1, which Premiere can't read reliably. After
a max-quality download we re-encode to H.264 with the Mac's hardware encoder
(VideoToolbox — fast, near-lossless at these bitrates), falling back to
libx264 if hardware encoding is unavailable.
"""

import json
import shutil
import subprocess
from pathlib import Path

# Codecs Premiere imports without drama. HEVC would qualify but YouTube never
# serves it, so anything not H.264 here is VP9/AV1.
SAFE_VCODECS = frozenset({"h264"})


def find_ffprobe(ffmpeg_path):
    """ffprobe ships next to ffmpeg; prefer the sibling, then PATH."""
    sibling = Path(str(ffmpeg_path)).parent / "ffprobe"
    if sibling.is_file():
        return str(sibling)
    return shutil.which("ffprobe")


def probe(ffprobe, path):
    """Return {vcodec, acodec, height, duration} or None if unreadable."""
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        info = json.loads(proc.stdout)
        streams = info.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if video is None:
            return None
        return {
            "vcodec": video.get("codec_name", ""),
            "acodec": audio.get("codec_name", "") if audio else "",
            "height": int(video.get("height") or 0),
            "duration": float(info.get("format", {}).get("duration") or 0.0),
        }
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        return None


def bitrate_for_height(height):
    """H.264 target bitrates generous enough to be visually transparent."""
    if height >= 2160:
        return "50M"
    if height >= 1440:
        return "28M"
    if height >= 1080:
        return "14M"
    if height >= 720:
        return "8M"
    return "5M"


def build_transcode_args(ffmpeg, src, dst, *, height, acodec, encoder="h264_videotoolbox"):
    argv = [
        str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
        "-nostats", "-progress", "pipe:1",
        "-i", str(src),
    ]
    if encoder == "h264_videotoolbox":
        argv += ["-c:v", "h264_videotoolbox", "-b:v", bitrate_for_height(height),
                 "-profile:v", "high"]
    else:
        argv += ["-c:v", "libx264", "-crf", "18", "-preset", "fast"]
    # 10-bit VP9/AV1 (HDR) must land as 8-bit for H.264 hardware paths.
    argv += ["-pix_fmt", "yuv420p"]
    argv += ["-c:a", "copy"] if acodec == "aac" else ["-c:a", "aac", "-b:a", "256k"]
    argv += ["-movflags", "+faststart", str(dst)]
    return argv


def parse_progress_line(line, duration):
    """ffmpeg -progress emits out_time_ms= in MICROseconds (historical quirk).
    Returns a 0..1 fraction, or None if the line isn't a progress line."""
    if not duration or not line.startswith("out_time_ms="):
        return None
    try:
        return min(int(line.split("=", 1)[1]) / 1e6 / duration, 1.0)
    except (ValueError, ZeroDivisionError):
        return None
