"""Filename construction: slugs, templates, and collision-safe paths."""

import re
import unicodedata
from pathlib import Path

_FORBIDDEN = set('/\\:*?"<>|')


def slugify(title, max_len=64):
    """Make a title safe for every filesystem Premiere might touch.

    Keeps case and unicode letters (readable in the Project panel), replaces
    separators and forbidden characters with single underscores.
    """
    out = []
    for ch in unicodedata.normalize("NFC", str(title or "")):
        if ch in _FORBIDDEN or unicodedata.category(ch)[0] == "C":
            out.append(" ")
        else:
            out.append(ch)
    text = "".join(out)
    text = re.sub(r"[\s_]+", "_", text.strip())
    text = text.strip("._")
    if len(text) > max_len:
        text = text[:max_len].rstrip("._")
    return text or "clip"


class _SafeFields(dict):
    def __missing__(self, key):
        return ""


def render_template(template, fields):
    """Fill a filename template; unknown tokens become empty, separators collapse."""
    try:
        name = str(template).format_map(_SafeFields(fields))
    except (ValueError, IndexError):  # malformed template like '{title'
        name = "_".join(str(v) for v in fields.values() if v)
    name = slugify(name, max_len=140)
    name = re.sub(r"_+", "_", name).strip("._-")
    return name or "clip"


def unique_path(directory, stem, ext=".mp4"):
    """Return a path in directory that does not exist yet: stem, stem_2, stem_3..."""
    directory = Path(directory)
    candidate = directory / f"{stem}{ext}"
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{n}{ext}"
        n += 1
    return candidate
