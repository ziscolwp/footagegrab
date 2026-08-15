"""Supervisor units for the PO-token provider sidecar.

Everything runs against a fake process, fake ping, and fake clock — no real
binary, no network. Cross-platform paths use the sys.platform-patch technique
from test_windows.py.
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab import potsidecar
from footagegrab.potsidecar import PotSupervisor


class FakeProc:
    def __init__(self):
        self.terminated = False
        self._rc = None

    def poll(self):
        return self._rc

    def terminate(self):
        self.terminated = True
        self._rc = 0

    def kill(self):
        self._rc = -9

    def die(self, rc=1):  # test helper: the sidecar crashed on its own
        self._rc = rc


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeTimer:
    """Records scheduling instead of running threads. Tests fire() manually."""

    def __init__(self, delay, fn):
        self.delay = delay
        self.fn = fn
        self.started = False
        self.canceled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.canceled = True

    def fire(self):
        self.fn()


class SupervisorHarness(unittest.TestCase):
    """Shared builder: a supervisor whose ping answers only while the last
    spawned fake process is alive (unless overridden per-test)."""

    def setUp(self):
        self.clock = FakeClock()
        self.timers = []
        self.spawned = []
        self.sleeps = []

    def fake_sleep(self, seconds):
        # advancing the clock keeps the supervisor's start-wait loop finite
        self.sleeps.append(seconds)
        self.clock.advance(seconds)

    def make(self, *, binary="/fake/bin/bgutil-pot", ping=None,
             spawn=None, **kwargs):
        def default_spawn(argv):
            self.spawned.append(argv)
            proc = FakeProc()
            self.procs.append(proc)
            return proc

        def default_ping():
            return bool(self.procs) and self.procs[-1].poll() is None

        def timer_factory(delay, fn):
            timer = FakeTimer(delay, fn)
            self.timers.append(timer)
            return timer

        self.procs = []
        return PotSupervisor(
            resolve=lambda: binary,
            spawn=spawn or default_spawn,
            ping=ping or default_ping,
            clock=self.clock,
            sleep=self.fake_sleep,
            timer_factory=timer_factory,
            **kwargs,
        )


class EnsureRunningTests(SupervisorHarness):
    def test_no_spawn_when_port_already_answers(self):
        sup = self.make(ping=lambda: True)
        self.assertTrue(sup.ensure_running())
        self.assertEqual(self.spawned, [])

    def test_spawns_binary_in_server_mode_when_port_dead(self):
        # without the "server" subcommand the binary runs one-shot CLI mode
        # and exits immediately (verified against v0.8.1 --help)
        sup = self.make()
        self.assertTrue(sup.ensure_running())
        self.assertEqual(self.spawned, [["/fake/bin/bgutil-pot", "server"]])

    def test_waits_for_slow_startup(self):
        # ping stays dead for the first three polls after spawn, then answers
        state = {"checks": 0}

        def slow_ping():
            if not self.procs:
                return False
            state["checks"] += 1
            return state["checks"] > 3

        sup = self.make(ping=slow_ping)
        self.assertTrue(sup.ensure_running())
        self.assertTrue(self.sleeps, "should have waited between ping polls")

    def test_missing_binary_degrades_tokenless(self):
        sup = self.make(binary=None)
        self.assertFalse(sup.ensure_running())
        self.assertEqual(self.spawned, [])

    def test_missing_binary_logs_once(self):
        sup = self.make(binary=None)
        with self.assertLogs("footagegrab.potsidecar", level="INFO") as logs:
            sup.ensure_running()
            sup.ensure_running()
        missing = [r for r in logs.output if "not installed" in r.lower()]
        self.assertEqual(len(missing), 1)

    def test_start_failures_are_bounded(self):
        sup = self.make(ping=lambda: False, start_timeout=1.0)
        for _ in range(5):
            self.assertFalse(sup.ensure_running())
        self.assertEqual(len(self.spawned), potsidecar.MAX_START_FAILURES)

    def test_failed_start_terminates_the_stuck_process(self):
        sup = self.make(ping=lambda: False, start_timeout=1.0)
        self.assertFalse(sup.ensure_running())
        self.assertTrue(self.procs[0].terminated)

    def test_success_resets_failure_budget(self):
        # two duds, then a healthy run, then death — restarts must still happen
        state = {"healthy": False}

        def ping():
            return state["healthy"] and self.procs and self.procs[-1].poll() is None

        sup = self.make(ping=ping, start_timeout=1.0)
        for _ in range(2):
            self.assertFalse(sup.ensure_running())
        state["healthy"] = True
        self.assertTrue(sup.ensure_running())
        self.procs[-1].die()
        self.assertTrue(sup.ensure_running(), "budget should reset on success")
        self.assertEqual(len(self.spawned), 4)

    def test_restarts_after_sidecar_death(self):
        sup = self.make()
        self.assertTrue(sup.ensure_running())
        self.procs[-1].die()
        self.assertTrue(sup.ensure_running())
        self.assertEqual(len(self.spawned), 2)

    def test_spawn_error_never_raises(self):
        def broken_spawn(argv):
            raise OSError("exec format error")

        sup = self.make(spawn=broken_spawn)
        self.assertFalse(sup.ensure_running())

    def test_ping_error_treated_as_down(self):
        def broken_ping():
            raise ConnectionError("boom")

        sup = self.make(ping=broken_ping, start_timeout=1.0)
        self.assertFalse(sup.ensure_running())  # must not raise


class StopTests(SupervisorHarness):
    def test_stop_terminates_owned_process(self):
        sup = self.make()
        sup.ensure_running()
        sup.stop()
        self.assertTrue(self.procs[0].terminated)

    def test_stop_without_process_is_safe(self):
        sup = self.make()
        sup.stop()  # nothing spawned; must not raise


class IdleShutdownTests(SupervisorHarness):
    def test_idle_timer_armed_on_successful_start(self):
        sup = self.make(idle_shutdown=900)
        sup.ensure_running()
        self.assertTrue(self.timers)
        self.assertEqual(self.timers[-1].delay, 900)
        self.assertTrue(self.timers[-1].started)

    def test_idle_expiry_stops_sidecar(self):
        sup = self.make(idle_shutdown=900)
        sup.ensure_running()
        self.clock.advance(900)
        self.timers[-1].fire()
        self.assertTrue(self.procs[0].terminated)

    def test_recent_activity_defers_shutdown(self):
        sup = self.make(idle_shutdown=900)
        sup.ensure_running()
        first = self.timers[-1]
        self.clock.advance(100)
        sup.ensure_running()  # a new grab counts as activity
        self.clock.advance(850)  # 850 idle since the second grab
        for timer in self.timers:
            if timer.started and not timer.canceled and timer is not first:
                timer.fire()
                break
        self.assertFalse(self.procs[0].terminated)

    def test_stale_timer_reschedules_remaining_idle(self):
        sup = self.make(idle_shutdown=900)
        sup.ensure_running()
        timer = self.timers[-1]
        self.clock.advance(400)
        sup.ensure_running()
        self.clock.advance(500)  # only 500 idle since latest activity
        live = [t for t in self.timers if t.started and not t.canceled][-1]
        live.fire()
        self.assertFalse(self.procs[0].terminated)
        self.assertEqual(self.timers[-1].delay, 400)  # 900 - 500 remaining

    def test_no_timer_for_external_server(self):
        # someone else runs a provider on the port — we never spawn, so we
        # must never try to shut it down either
        sup = self.make(ping=lambda: True, idle_shutdown=900)
        sup.ensure_running()
        self.assertEqual(self.timers, [])


class BinaryResolutionTests(unittest.TestCase):
    def test_default_path_darwin(self):
        with mock.patch.object(sys, "platform", "darwin"), \
             mock.patch.dict(os.environ, {"FOOTAGEGRAB_HOME": "/tmp/fg-pot"}):
            path = potsidecar.default_binary_path()
        self.assertEqual(str(path), str(Path("/tmp/fg-pot") / "bin" / "bgutil-pot"))

    def test_default_path_windows_gets_exe_suffix(self):
        with mock.patch.object(sys, "platform", "win32"), \
             mock.patch.dict(os.environ, {"FOOTAGEGRAB_HOME": "/tmp/fg-pot"}):
            path = potsidecar.default_binary_path()
        self.assertEqual(path.name, "bgutil-pot.exe")

    def test_config_override_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "my-pot-provider"
            override.write_text("#!/bin/sh\n")
            override.chmod(override.stat().st_mode | stat.S_IEXEC)
            resolved = potsidecar.resolve_binary({"pot_provider_path": str(override)})
        self.assertEqual(resolved, str(override))

    def test_missing_binary_resolves_none(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(os.environ, {"FOOTAGEGRAB_HOME": tmp}):
            self.assertIsNone(potsidecar.resolve_binary({}))


STUB_YTDLP = """#!/bin/bash
out=""
prev=""
for a in "$@"; do
  if [ "$prev" = "-o" ]; then out="$a"; fi
  prev="$a"
done
echo "[download] 100% of 1.00MiB"
printf 'fake video bytes' > "$out"
exit 0
"""


class FakePot:
    def __init__(self, available=True):
        self.available = available
        self.ensure_calls = 0

    def ensure_running(self):
        self.ensure_calls += 1
        return self.available


@unittest.skipIf(sys.platform == "win32", "bash stub")
class RunnerWiringTests(unittest.TestCase):
    def _run_job(self, pot):
        from footagegrab.jobs import Job
        from footagegrab.runner import DownloadRunner

        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "ytdlp-stub"
            stub.write_text(STUB_YTDLP)
            stub.chmod(0o755)
            cfg = {
                "destinations": [{"id": "d1", "label": "test", "path": tmp}],
                "destination_id": "d1",
                "quality": "max", "accurate_cut": False,
                "compat_transcode": False, "cookies_browser": "none",
                "template_segment": "{title} {n}", "template_full": "{title} {n}",
                "ytdlp_path": str(stub), "ffmpeg_path": "/bin/ls",
            }
            runner = DownloadRunner(lambda: cfg, pot=pot)
            job = Job(url="https://www.youtube.com/watch?v=x", video_id="x",
                      title="Clip", mode="full")
            return runner.run(job)

    def test_sidecar_ensured_before_grab(self):
        pot = FakePot()
        ok, error, final = self._run_job(pot)
        self.assertTrue(ok, error)
        self.assertEqual(pot.ensure_calls, 1)

    def test_grab_succeeds_when_sidecar_unavailable(self):
        pot = FakePot(available=False)
        ok, error, final = self._run_job(pot)
        self.assertTrue(ok, error)
        self.assertEqual(pot.ensure_calls, 1)

    def test_runner_survives_a_raising_supervisor(self):
        class ExplodingPot:
            def ensure_running(self):
                raise RuntimeError("supervisor bug")

        ok, error, final = self._run_job(ExplodingPot())
        self.assertTrue(ok, error)


if __name__ == "__main__":
    unittest.main()
