"""Config, paths, and tool resolution for the native host.

Everything lives under ~/Library/Application Support/FootageGrab (override with
FOOTAGEGRAB_HOME for tests). Chrome launches native hosts with a minimal PATH
that misses Homebrew, so we augment PATH before resolving yt-dlp/ffmpeg.
"""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

DEFAULTS = {
    "output_dir": "~/Movies/FootageGrab" if sys.platform == "darwin" else "~/Videos/FootageGrab",
    # Written by the Premiere panel's "Save next to project" mode; wins over
    # output_dir while non-empty AND freshly heartbeated (see PROJECT_CLAIM_TTL)
    # — so a panel that quit without cleaning up can't redirect downloads
    # forever. The user's global output_dir is never touched.
    "project_output_dir": "",
    "project_output_dir_ts": 0,  # unix seconds of the panel's last heartbeat
    "quality": "max",  # max | 1080 | 720  ("best" is a legacy alias for max)
    "accurate_cut": False,
    "compat_transcode": True,  # convert VP9/AV1 (all 4K+) to H.264 for Premiere
    "cookies_browser": "none",  # none | chrome | brave | chromium | edge
    "template_segment": "{title} {n}",
    "template_full": "{title} {n}",
    "ask_names": False,  # prompt for a clip name at grab time
    "max_concurrent": 2,
    "ytdlp_path": "",
    "ffmpeg_path": "",
    # PO-token sidecar (see potsidecar.py): binary override + idle shutdown
    "pot_provider_path": "",
    "pot_idle_shutdown": 900,  # seconds
}

VALID_QUALITY = ("max", "1080", "720", "best")
VALID_COOKIES = ("none", "chrome", "brave", "chromium", "edge")
if sys.platform == "win32":
    # winget/scoop/chocolatey shims — Chrome passes the user PATH on Windows,
    # but freshly-installed tools may predate the current session's PATH.
    EXTRA_PATH = tuple(p for p in (
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
        os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
        r"C:\ProgramData\chocolatey\bin",
    ) if "%" not in p)
else:
    EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")


def app_home():
    override = os.environ.get("FOOTAGEGRAB_HOME")
    if override:
        home = Path(override)
    elif sys.platform == "darwin":
        home = Path.home() / "Library" / "Application Support" / "FootageGrab"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        home = base / "FootageGrab"
    else:
        home = Path.home() / ".config" / "footagegrab"
    home.mkdir(parents=True, exist_ok=True)
    return home


def config_path():
    return app_home() / "config.json"


def logs_dir():
    d = app_home() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def history_path():
    return app_home() / "history.jsonl"


def load():
    cfg = dict(DEFAULTS)
    try:
        stored = json.loads(config_path().read_text("utf-8"))
        if isinstance(stored, dict):
            cfg.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, json.JSONDecodeError):
        pass
    if cfg.get("quality") == "best":  # pre-0.2 configs
        cfg["quality"] = "max"
    return cfg


def save(cfg):
    path = config_path()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def update(patch):
    """Apply a whitelisted, validated patch. Returns (config, errors)."""
    cfg = load()
    errors = []
    for key, value in (patch or {}).items():
        if key not in DEFAULTS:
            errors.append(f"unknown setting: {key}")
            continue
        if key == "quality":
            if value not in VALID_QUALITY:
                errors.append(f"quality must be one of {', '.join(VALID_QUALITY)}")
                continue
            if value == "best":
                value = "max"
        if key == "cookies_browser" and value not in VALID_COOKIES:
            errors.append(f"cookies_browser must be one of {', '.join(VALID_COOKIES)}")
            continue
        if key in ("accurate_cut", "compat_transcode", "ask_names"):
            value = bool(value)
        if key == "max_concurrent":
            try:
                value = max(1, min(4, int(value)))
            except (TypeError, ValueError):
                errors.append("max_concurrent must be a number")
                continue
        if key == "pot_idle_shutdown":
            try:
                value = max(60, min(7200, int(value)))
            except (TypeError, ValueError):
                errors.append("pot_idle_shutdown must be a number of seconds")
                continue
        if key in ("output_dir", "project_output_dir", "template_segment",
                   "template_full", "ytdlp_path", "ffmpeg_path",
                   "pot_provider_path"):
            value = str(value).strip()
            if key.startswith("template") and not value:
                errors.append(f"{key} cannot be empty")
                continue
            if key == "output_dir" and not value:
                errors.append("output_dir cannot be empty")
                continue
        cfg[key] = value
    save(cfg)
    return cfg, errors


# The panel refreshes its claim roughly every 30s while alive; three missed
# heartbeats means it is gone (Premiere quit, panel closed, machine slept).
PROJECT_CLAIM_TTL = 90


def project_claim_fresh(cfg, now=None):
    """True while the Premiere panel's project-folder claim is heartbeated."""
    if not str(cfg.get("project_output_dir") or "").strip():
        return False
    try:
        ts = float(cfg.get("project_output_dir_ts") or 0)
    except (TypeError, ValueError):
        return False
    now = time.time() if now is None else now
    return abs(now - ts) <= PROJECT_CLAIM_TTL


def effective_output_dir(cfg):
    """The folder downloads actually use (unexpanded): a live project claim
    wins, else the user's own output_dir."""
    if project_claim_fresh(cfg):
        return str(cfg["project_output_dir"]).strip()
    return str(cfg.get("output_dir") or DEFAULTS["output_dir"])


def ensure_output_dir(cfg):
    """Expand, create, and sanity-check the output folder. Raises OSError."""
    path = Path(effective_output_dir(cfg)).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    if not os.access(path, os.W_OK):
        raise OSError(f"not writable: {path}")
    return path


def augment_path():
    """Prepend Homebrew/MacPorts locations Chrome strips from PATH."""
    current = os.environ.get("PATH", "")
    parts = [p for p in current.split(os.pathsep) if p]
    for extra in reversed(EXTRA_PATH):
        if extra not in parts:
            parts.insert(0, extra)
    os.environ["PATH"] = os.pathsep.join(parts)


def resolve_tool(name, override=""):
    """Absolute path for a tool: explicit config override wins, then PATH."""
    override = str(override or "").strip()
    if override:
        p = Path(override).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        return None
    return shutil.which(name)
