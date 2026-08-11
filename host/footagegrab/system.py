"""macOS integration: Finder reveal, native folder picker, tool health, updates."""

import subprocess
import sys
from pathlib import Path

from . import config


def _run(argv, timeout):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def reveal(path):
    """Reveal a file in Finder. Returns (ok, error)."""
    p = Path(str(path)).expanduser()
    if not p.exists():
        return False, f"file no longer exists: {p}"
    if sys.platform != "darwin":
        return False, "reveal is only supported on macOS"
    _run(["open", "-R", str(p)], timeout=10)
    return True, ""


def open_folder(path):
    p = Path(str(path)).expanduser()
    if not p.is_dir():
        return False, f"folder does not exist: {p}"
    if sys.platform != "darwin":
        return False, "open is only supported on macOS"
    _run(["open", str(p)], timeout=10)
    return True, ""


def choose_folder(prompt="Choose your FootageGrab footage folder"):
    """Native folder picker via osascript. Returns (path | None, error)."""
    if sys.platform != "darwin":
        return None, "folder picker is only supported on macOS"
    script = f'POSIX path of (choose folder with prompt "{prompt}")'
    try:
        proc = _run(["osascript", "-e", script], timeout=240)
    except subprocess.TimeoutExpired:
        return None, "folder picker timed out"
    if proc.returncode == 0:
        path = proc.stdout.strip()
        return (path, "") if path else (None, "no folder returned")
    if "User canceled" in (proc.stderr or ""):
        return None, "canceled"
    return None, (proc.stderr or "folder picker failed").strip()[:200]


def tool_version(path, flag="--version"):
    try:
        proc = _run([path, flag], timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    first = (proc.stdout or proc.stderr).strip().splitlines()
    return first[0][:120] if first else ""


def health(cfg):
    """Everything the popup needs to say whether grabbing will work."""
    ytdlp = config.resolve_tool("yt-dlp", cfg.get("ytdlp_path"))
    ffmpeg = config.resolve_tool("ffmpeg", cfg.get("ffmpeg_path"))
    out = {"path": "", "exists": False, "writable": False}
    try:
        d = config.ensure_output_dir(cfg)
        out = {"path": str(d), "exists": True, "writable": True}
    except OSError as exc:
        out["path"] = str(exc)
    return {
        "ytdlp": {"path": ytdlp or "", "version": tool_version(ytdlp) if ytdlp else "",
                  "found": bool(ytdlp)},
        "ffmpeg": {"path": ffmpeg or "", "version": tool_version(ffmpeg, "-version") if ffmpeg else "",
                   "found": bool(ffmpeg)},
        "output": out,
        "logs": str(config.logs_dir() / "host.log"),
    }


def update_ytdlp(cfg):
    """Run yt-dlp -U. Homebrew installs refuse -U; surface the brew command."""
    ytdlp = config.resolve_tool("yt-dlp", cfg.get("ytdlp_path"))
    if not ytdlp:
        return {"ok": False, "output": "yt-dlp not found"}
    try:
        proc = _run([ytdlp, "-U"], timeout=300)
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "update timed out"}
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if "brew" in output.lower() or "/opt/homebrew" in ytdlp:
        output += "\n\nHomebrew install detected — update with: brew upgrade yt-dlp"
    return {"ok": proc.returncode == 0, "output": output[-800:]}
