import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab import config, system


class MarkCloudIgnoredTests(unittest.TestCase):
    def test_marking_a_real_folder_reports_success_on_supported_platforms(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = system.mark_cloud_ignored(Path(tmp))
            if sys.platform in ("darwin", "win32"):
                self.assertTrue(result)
            else:
                self.assertFalse(result)

    def test_marking_a_missing_path_returns_false_and_does_not_raise(self):
        self.assertFalse(system.mark_cloud_ignored(Path("/no/such/folder/anywhere")))


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("FOOTAGEGRAB_HOME")
        os.environ["FOOTAGEGRAB_HOME"] = self.tmp.name

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("FOOTAGEGRAB_HOME", None)
        else:
            os.environ["FOOTAGEGRAB_HOME"] = self._old_home
        self.tmp.cleanup()

    def test_health_reports_a_missing_destination_without_creating_it(self):
        missing = Path(self.tmp.name) / "not-yet-mounted"
        cfg, _ = config.add_destination(str(missing))

        out = system.health(cfg)["output"]

        self.assertEqual(out["path"], str(missing))
        self.assertFalse(out["exists"])
        self.assertFalse(out["writable"])
        self.assertFalse(missing.exists(), "health() must not create the destination")
