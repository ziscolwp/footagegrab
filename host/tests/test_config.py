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

    def test_project_output_dir_wins_while_claim_is_fresh(self):
        import time
        proj = Path(self.tmp.name) / "MyDoc" / "FootageGrab"
        cfg = {"output_dir": str(Path(self.tmp.name) / "global"),
               "project_output_dir": str(proj),
               "project_output_dir_ts": time.time()}
        out = config.ensure_output_dir(cfg)
        self.assertEqual(out, proj)
        self.assertTrue(proj.is_dir())

    def test_stale_project_claim_falls_back_to_global(self):
        import time
        glob = Path(self.tmp.name) / "global"
        cfg = {"output_dir": str(glob),
               "project_output_dir": str(Path(self.tmp.name) / "Old" / "FootageGrab"),
               "project_output_dir_ts": time.time() - 3600}  # panel long gone
        self.assertEqual(config.ensure_output_dir(cfg), glob)

    def test_missing_claim_timestamp_falls_back_to_global(self):
        glob = Path(self.tmp.name) / "global"
        cfg = {"output_dir": str(glob),
               "project_output_dir": str(Path(self.tmp.name) / "Old" / "FootageGrab")}
        self.assertEqual(config.ensure_output_dir(cfg), glob)

    def test_empty_project_output_dir_falls_back(self):
        glob = Path(self.tmp.name) / "global"
        cfg = {"output_dir": str(glob), "project_output_dir": ""}
        self.assertEqual(config.ensure_output_dir(cfg), glob)

    def test_project_output_dir_survives_load_roundtrip(self):
        config.save({"output_dir": "~/x", "project_output_dir": "/p/FootageGrab"})
        cfg = config.load()
        self.assertEqual(cfg["project_output_dir"], "/p/FootageGrab")

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
