"""Multi-site metadata: yt-dlp title/id/site prefetch and error hints.

Context-menu and adapter grabs arrive with just a URL — no title, no id. A
quick ``yt-dlp --print`` (implies simulate: no download) fills the naming
pipeline. Prefetch failure never fails a job; naming falls back to site+date.
"""

import subprocess
from urllib.parse import urlparse

SEP = "\x1f"  # unit separator: never appears in titles
PRINT_TEMPLATE = f"%(title)s{SEP}%(id)s{SEP}%(extractor_key)s"
DEFAULT_TIMEOUT = 20

# hostname second-level label -> canonical site token (matches yt-dlp
# extractor keys, lowercased). Anything unlisted uses the label itself.
_SITE_ALIASES = {
    "x": "twitter",
    "twitter": "twitter",
    "youtube": "youtube",
    "youtu": "youtube",  # youtu.be
    "reddit": "reddit",
    "redd": "reddit",  # v.redd.it
    "tiktok": "tiktok",
    "instagram": "instagram",
}

_LOGIN_MARKERS = (
    "sign in", "log in", "login", "logged in", "authentication",
    "cookies", "registered users", "private video", "nsfw",
)
COOKIE_HINT = "Enable Browser cookies in FootageGrab Settings and retry."


def site_from_url(url):
    """Cheap site token from the hostname — used until (or instead of) the
    extractor key from a prefetch. Always returns something template-safe."""
    host = (urlparse(str(url or "")).hostname or "").lower()
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return "site"
    label = parts[-2]
    return _SITE_ALIASES.get(label, label)


def parse_print_output(text):
    """Parse `--print title\\x1fid\\x1fextractor_key` stdout. None if absent."""
    for line in reversed(str(text or "").strip().splitlines()):
        if SEP not in line:
            continue
        parts = line.split(SEP)
        if len(parts) < 3:
            continue

        def clean(value):
            value = value.strip()
            return "" if value in ("", "NA") else value

        return {
            "title": clean(parts[0]),
            "id": clean(parts[1])[:32],
            "site": clean(parts[2]).lower(),
        }
    return None


def fetch_metadata(ytdlp_path, url, cookies_browser=None, timeout=DEFAULT_TIMEOUT):
    """Run yt-dlp to resolve title/id/site. Returns a dict or None — callers
    must treat None as 'name it site_date and download anyway'."""
    argv = [str(ytdlp_path), "--no-playlist", "--print", PRINT_TEMPLATE]
    if cookies_browser and cookies_browser != "none":
        argv += ["--cookies-from-browser", cookies_browser]
    argv.append(str(url))
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, errors="replace", timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return parse_print_output(proc.stdout)


def hint_for_error(text):
    """A human next-step for login-walled downloads, or empty string."""
    lowered = str(text or "").lower()
    if any(marker in lowered for marker in _LOGIN_MARKERS):
        return COOKIE_HINT
    return ""
