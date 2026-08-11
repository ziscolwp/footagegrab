"""OS integration: file-manager reveal, native folder picker, tool health,
updates. macOS uses open/osascript; Windows uses explorer/PowerShell."""

import subprocess
import sys
from pathlib import Path

from . import config


def _run(argv, timeout):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def reveal(path):
    """Reveal a file in Finder / Explorer. Returns (ok, error)."""
    p = Path(str(path)).expanduser()
    if not p.exists():
        return False, f"file no longer exists: {p}"
    if sys.platform == "darwin":
        _run(["open", "-R", str(p)], timeout=10)
        return True, ""
    if sys.platform == "win32":
        # explorer exits non-zero even on success — fire and forget
        subprocess.Popen(["explorer", f"/select,{p}"])
        return True, ""
    return False, "reveal is not supported on this platform"


def open_folder(path):
    p = Path(str(path)).expanduser()
    if not p.is_dir():
        return False, f"folder does not exist: {p}"
    if sys.platform == "darwin":
        _run(["open", str(p)], timeout=10)
        return True, ""
    if sys.platform == "win32":
        import os
        os.startfile(str(p))  # noqa: S606 — opening the user's own folder
        return True, ""
    return False, "open is not supported on this platform"


_PS_PICKER = """
Add-Type -AssemblyName System.Windows.Forms | Out-Null
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = 'Choose your FootageGrab footage folder'
$d.ShowNewFolderButton = $true
if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::Out.Write($d.SelectedPath)
}
"""


def choose_folder(prompt="Choose your FootageGrab footage folder"):
    """Native folder picker. Returns (path | None, error)."""
    if sys.platform == "darwin":
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
    if sys.platform == "win32":
        try:
            proc = _run(["powershell", "-NoProfile", "-STA", "-Command", _PS_PICKER],
                        timeout=240)
        except (subprocess.TimeoutExpired, OSError):
            return None, "folder picker timed out"
        path = (proc.stdout or "").strip()
        if proc.returncode == 0 and path:
            return path, ""
        return None, "canceled"
    return None, "folder picker is not supported on this platform"


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
    """Run yt-dlp -U. Package-manager installs refuse -U; surface the command."""
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
    elif sys.platform == "win32" and proc.returncode != 0:
        output += "\n\nIf installed with winget, update with: winget upgrade yt-dlp"
    return {"ok": proc.returncode == 0, "output": output[-800:]}
