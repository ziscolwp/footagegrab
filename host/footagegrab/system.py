"""OS integration: file-manager reveal, native folder picker, tool health,
updates. macOS uses open/osascript; Windows uses explorer/PowerShell."""

import subprocess
import sys
from pathlib import Path

from . import config


def _run(argv, timeout):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def mark_cloud_ignored(path):
    """Tell Dropbox to skip this folder. Best effort — returns True if marked.

    macOS uses an extended attribute; Windows the same-named alternate data
    stream. Failure is not fatal: delivery is still atomic, the temp folder
    just syncs.

    macOS note: CPython's os.setxattr is Linux-only (not exposed on Darwin),
    so the attribute is written via the `xattr` CLI that ships with macOS
    instead. Invoked by absolute path (/usr/bin/xattr): config.augment_path()
    prepends /opt/homebrew/bin to PATH for yt-dlp/ffmpeg resolution, and a
    Homebrew-installed xattr would otherwise shadow the system one.
    """
    path = Path(path)
    if not path.exists():
        return False
    try:
        if sys.platform == "darwin":
            proc = _run(["/usr/bin/xattr", "-w", "com.dropbox.ignored", "1", str(path)],
                        timeout=10)
            return proc.returncode == 0
        if sys.platform == "win32":
            with open(f"{path}:com.dropbox.ignored", "w", encoding="ascii") as f:
                f.write("1")
            return True
    except (OSError, subprocess.SubprocessError):
        return False
    return False


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
    path = Path(config.effective_output_dir(cfg)).expanduser()
    try:
        config.validate_output_dir(cfg)
        exists, writable = True, True
    except OSError:
        # Missing and unwritable both raise here; a folder that exists but
        # isn't writable still reports exists so the popup doesn't tell the
        # user to go create something that's already there.
        exists, writable = path.is_dir(), False
    out = {"path": str(path), "exists": exists, "writable": writable}
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
