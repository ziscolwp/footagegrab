"""Lifecycle supervisor for the bgutil PO-token provider sidecar.

The sidecar (a single Rust binary, installed by install/) serves GVS PO tokens
over HTTP on 127.0.0.1:4416; the bgutil yt-dlp plugin picks them up from there
automatically. A live sidecar upgrades the mweb player client from progressive
360p to full adaptive streams. The supervisor's one hard rule: a grab must
never fail because the sidecar is unavailable — every failure path here
degrades to tokenless and lets the download proceed.

Process, port, clock, and timers are injectable so the whole lifecycle is
unit-testable without a real binary or network (see tests/test_potsidecar.py).
"""

import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config

log = logging.getLogger("footagegrab.potsidecar")

# Fixed by the bgutil plugin's default; changing it would need extractor-arg
# plumbing on every yt-dlp invocation for no benefit.
DEFAULT_PORT = 4416

# Idle period before the sidecar is shut down (settled 2026-08-15): long
# enough to cover inter-grab gaps in an editing session, short enough that it
# is gone once the user walks away. Overridable via config pot_idle_shutdown.
DEFAULT_IDLE_SHUTDOWN = 900

START_TIMEOUT = 8.0  # BotGuard warmup takes a few seconds on first launch
PING_TIMEOUT = 1.0
POLL_INTERVAL = 0.25
MAX_START_FAILURES = 3  # then disabled for the session — no infinite respawn


def default_binary_path():
    """Where the installer puts the provider: next to the host launcher."""
    name = "bgutil-pot.exe" if sys.platform == "win32" else "bgutil-pot"
    return config.app_home() / "bin" / name


def resolve_binary(cfg):
    """Absolute provider path, or None when not installed. An explicit
    pot_provider_path override wins, mirroring ytdlp_path/ffmpeg_path."""
    override = str((cfg or {}).get("pot_provider_path") or "").strip()
    candidate = Path(override).expanduser() if override else default_binary_path()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def _http_ping(port):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/ping", timeout=PING_TIMEOUT
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _default_spawn(argv):
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, **kwargs,
    )


def _default_timer(delay, fn):
    timer = threading.Timer(delay, fn)
    timer.daemon = True
    return timer


class PotSupervisor:
    """Starts the provider lazily, restarts it after death, shuts it down
    when idle, and gives up (for the session) after repeated failed starts."""

    def __init__(self, resolve=None, *, port=DEFAULT_PORT,
                 idle_shutdown=DEFAULT_IDLE_SHUTDOWN,
                 start_timeout=START_TIMEOUT, max_failures=MAX_START_FAILURES,
                 spawn=None, ping=None, clock=time.monotonic, sleep=time.sleep,
                 timer_factory=None):
        self._resolve = resolve or (lambda: resolve_binary(config.load()))
        self._port = port
        self._idle_shutdown = idle_shutdown
        self._start_timeout = start_timeout
        self._max_failures = max_failures
        self._spawn = spawn or _default_spawn
        self._ping = ping or (lambda: _http_ping(port))
        self._clock = clock
        self._sleep = sleep
        self._timer_factory = timer_factory or _default_timer
        self._lock = threading.RLock()
        self._proc = None
        self._timer = None
        self._last_activity = 0.0
        self._failures = 0
        self._missing_logged = False
        self._broken_logged = False

    def ensure_running(self):
        """True when a provider answers on the port (started here or not).
        False means this grab runs tokenless. Never raises."""
        with self._lock:
            try:
                return self._ensure_locked()
            except Exception:
                log.warning("PO token supervisor error — grabbing tokenless",
                            exc_info=True)
                return False

    def stop(self):
        """Shut down an owned provider process. Safe when nothing runs."""
        with self._lock:
            self._cancel_timer()
            self._terminate()

    # -- internals (all called with the lock held) ---------------------------

    def _ensure_locked(self):
        if self._ping_ok():
            self._failures = 0
            self._note_activity()
            return True
        binary = self._resolve()
        if not binary:
            if not self._missing_logged:
                self._missing_logged = True
                log.info("PO token provider not installed — grabbing tokenless"
                         " (re-run the installer to add it)")
            return False
        if self._failures >= self._max_failures:
            if not self._broken_logged:
                self._broken_logged = True
                log.warning("PO token sidecar failed to start %s times — "
                            "disabled until the host restarts", self._failures)
            return False
        self._terminate()  # reap a dead child before replacing it
        try:
            # "server" is required: the bare binary is a one-shot CLI token
            # generator that exits immediately
            proc = self._spawn([binary, "server"])
        except OSError as exc:
            self._failures += 1
            log.warning("could not start PO token sidecar: %s", exc)
            return False
        deadline = self._clock() + self._start_timeout
        while self._clock() < deadline and proc.poll() is None:
            if self._ping_ok():
                self._proc = proc
                self._failures = 0
                self._note_activity()
                log.info("PO token sidecar up on port %s", self._port)
                return True
            self._sleep(POLL_INTERVAL)
        self._failures += 1
        log.warning("PO token sidecar not answering on port %s "
                    "(attempt %s/%s) — grabbing tokenless",
                    self._port, self._failures, self._max_failures)
        try:
            proc.terminate()
        except Exception:
            pass
        return False

    def _ping_ok(self):
        try:
            return bool(self._ping())
        except Exception:
            return False

    def _note_activity(self):
        self._last_activity = self._clock()
        # only arm the idle timer for a process we own — an externally-run
        # provider on the same port is not ours to shut down
        if self._proc is not None and self._proc.poll() is None:
            self._arm_timer(self._idle_shutdown)

    def _arm_timer(self, delay):
        self._cancel_timer()
        self._timer = self._timer_factory(delay, self._on_idle_timer)
        self._timer.start()

    def _cancel_timer(self):
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None

    def _on_idle_timer(self):
        with self._lock:
            self._timer = None
            if self._proc is None or self._proc.poll() is not None:
                self._proc = None
                return
            idle = self._clock() - self._last_activity
            if idle >= self._idle_shutdown:
                log.info("PO token sidecar idle for %.0fs — shutting down", idle)
                self._terminate()
            else:
                self._arm_timer(self._idle_shutdown - idle)

    def _terminate(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
