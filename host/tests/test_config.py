import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab import config


class ConfigTests(unittest.TestCase):
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

    def test_defaults(self):
        cfg = config.load()
        self.assertEqual(cfg["quality"], "max")
        self.assertTrue(cfg["compat_transcode"])

    def test_legacy_best_normalized_on_load(self):
        (Path(self.tmp.name) / "config.json").write_text(json.dumps({"quality": "best"}))
        self.assertEqual(config.load()["quality"], "max")

    def test_update_normalizes_and_validates_quality(self):
        cfg, errors = config.update({"quality": "best"})
        self.assertEqual((cfg["quality"], errors), ("max", []))
        cfg, errors = config.update({"quality": "4k"})
        self.assertEqual(cfg["quality"], "max", "invalid value must not stick")
        self.assertTrue(errors)

    def test_compat_transcode_coerced_to_bool(self):
        cfg, errors = config.update({"compat_transcode": 0})
        self.assertIs(cfg["compat_transcode"], False)
        self.assertEqual(errors, [])
        cfg, _ = config.update({"compat_transcode": "yes"})
        self.assertIs(cfg["compat_transcode"], True)


if __name__ == "__main__":
    unittest.main()
