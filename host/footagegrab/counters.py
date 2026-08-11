"""Per-video sequence numbers backing the {n} filename token.

Grabbing three sections of one video names them "Title 1/2/3" in mark order.
Counters persist in counters.json so numbering continues across sessions,
keyed by video id (or URL when no id is known yet).
"""

import json
import os
import tempfile
import threading

from . import config

_lock = threading.Lock()


def counters_path():
    return config.app_home() / "counters.json"


def next_index(key):
    """1-based, monotonically increasing per key. Thread-safe, persistent."""
    key = str(key)
    with _lock:
        try:
            data = json.loads(counters_path().read_text("utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        n = int(data.get(key, 0)) + 1
        data[key] = n
        path = counters_path()
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".counters-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return n
