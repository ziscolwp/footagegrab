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
from pathlib import Path

DEFAULTS = {
    "output_dir": "~/Movies/FootageGrab",
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
}

VALID_QUALITY = ("max", "1080", "720", "best")
VALID_COOKIES = ("none", "chrome", "brave", "chromium", "edge")
EXTRA_PATH = ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin")


def app_home():
    override = os.environ.get("FOOTAGEGRAB_HOME")
    if override:
        home = Path(override)
    elif sys.platform == "darwin":
        home = Path.home() / "Library" / "Application Support" / "FootageGrab"
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
        if key in ("output_dir", "template_segment", "template_full", "ytdlp_path", "ffmpeg_path"):
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


def ensure_output_dir(cfg):
    """Expand, create, and sanity-check the output folder. Raises OSError."""
    path = Path(str(cfg.get("output_dir") or DEFAULTS["output_dir"])).expanduser()
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
