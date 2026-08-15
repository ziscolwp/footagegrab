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
    # Saved footage folders, chosen from the extension. The legacy single
    # output_dir migrates in as the first entry on load — see _migrate.
    "destinations": [],          # [{"id": str, "label": str, "path": str}]
    "destination_id": "",        # id of the selected entry, "" when none
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

DEFAULT_DESTINATION = (
    "~/Movies/FootageGrab" if sys.platform == "darwin" else "~/Videos/FootageGrab"
)

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
    cfg["destinations"] = []
    stored = {}
    try:
        parsed = json.loads(config_path().read_text("utf-8"))
        if isinstance(parsed, dict):
            stored = parsed
            cfg.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, json.JSONDecodeError):
        pass
    if cfg.get("quality") == "best":  # pre-0.2 configs
        cfg["quality"] = "max"
    return _migrate(cfg, stored)


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
        if key in ("template_segment", "template_full", "ytdlp_path",
                   "ffmpeg_path", "pot_provider_path"):
            value = str(value).strip()
            if key.startswith("template") and not value:
                errors.append(f"{key} cannot be empty")
                continue
        cfg[key] = value
    save(cfg)
    return cfg, errors


def _new_id(existing):
    """Short, stable, collision-free id for a destination entry."""
    n = 1
    taken = {d.get("id") for d in existing}
    while f"d{n}" in taken:
        n += 1
    return f"d{n}"


def _migrate(cfg, stored):
    """Fold a pre-destinations config forward. Mutates and returns cfg."""
    if cfg.get("destinations"):
        return cfg
    legacy = str(stored.get("output_dir") or "").strip()
    if not legacy:
        return cfg
    entry = {"id": "d1", "label": Path(legacy).name or legacy, "path": legacy}
    cfg["destinations"] = [entry]
    cfg["destination_id"] = entry["id"]
    return cfg


def destinations(cfg):
    """The saved folders, as a list of {id, label, path} dicts."""
    raw = cfg.get("destinations")
    if not isinstance(raw, list):
        return []
    return [d for d in raw if isinstance(d, dict) and d.get("id") and d.get("path")]


def selected_destination(cfg):
    """The chosen entry, or None when the list is empty."""
    entries = destinations(cfg)
    if not entries:
        return None
    for entry in entries:
        if entry["id"] == cfg.get("destination_id"):
            return entry
    return entries[0]


def add_destination(path, label=""):
    """Append a folder and select it. Returns (config, entry)."""
    cfg = load()
    path = str(path).strip()
    entries = destinations(cfg)
    entry = {
        "id": _new_id(entries),
        "label": str(label).strip() or Path(path).name or path,
        "path": path,
    }
    entries.append(entry)
    cfg["destinations"] = entries
    cfg["destination_id"] = entry["id"]
    save(cfg)
    return cfg, entry


def remove_destination(dest_id):
    """Drop a folder. Returns (config, error). Selection falls back to first."""
    cfg = load()
    entries = destinations(cfg)
    kept = [d for d in entries if d["id"] != dest_id]
    if len(kept) == len(entries):
        return cfg, f"unknown destination: {dest_id}"
    cfg["destinations"] = kept
    if cfg.get("destination_id") == dest_id:
        cfg["destination_id"] = kept[0]["id"] if kept else ""
    save(cfg)
    return cfg, ""


def select_destination(dest_id):
    """Choose a folder. Returns (config, error)."""
    cfg = load()
    if not any(d["id"] == dest_id for d in destinations(cfg)):
        return cfg, f"unknown destination: {dest_id}"
    cfg["destination_id"] = dest_id
    save(cfg)
    return cfg, ""


def effective_output_dir(cfg):
    """The folder downloads use (unexpanded)."""
    entry = selected_destination(cfg)
    return entry["path"] if entry else DEFAULT_DESTINATION


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
