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

    def test_pot_sidecar_defaults(self):
        cfg = config.load()
        self.assertEqual(cfg["pot_provider_path"], "")
        self.assertEqual(cfg["pot_idle_shutdown"], 900)

    def test_pot_provider_path_accepts_and_strips_string(self):
        cfg, errors = config.update({"pot_provider_path": "  /opt/bgutil-pot  "})
        self.assertEqual((cfg["pot_provider_path"], errors), ("/opt/bgutil-pot", []))

    def test_pot_idle_shutdown_clamped_to_sane_seconds(self):
        cfg, errors = config.update({"pot_idle_shutdown": 5})
        self.assertEqual((cfg["pot_idle_shutdown"], errors), (60, []))
        cfg, _ = config.update({"pot_idle_shutdown": 999999})
        self.assertEqual(cfg["pot_idle_shutdown"], 7200)
        cfg, errors = config.update({"pot_idle_shutdown": "soon"})
        self.assertTrue(errors)

    def test_legacy_output_dir_migrates_to_a_selected_destination(self):
        legacy = str(Path(self.tmp.name) / "old-folder")
        config.save({"output_dir": legacy, "quality": "max"})
        cfg = config.load()
        dests = config.destinations(cfg)
        self.assertEqual(len(dests), 1)
        self.assertEqual(dests[0]["path"], legacy)
        self.assertEqual(dests[0]["label"], "old-folder")
        self.assertEqual(cfg["destination_id"], dests[0]["id"])
        self.assertEqual(config.effective_output_dir(cfg), legacy)

    def test_project_claim_fields_are_dropped_on_migration(self):
        config.save({"output_dir": "~/a", "project_output_dir": "/tmp/claimed",
                     "project_output_dir_ts": 9e9})
        cfg = config.load()
        self.assertNotIn("project_output_dir", cfg)
        self.assertEqual(config.effective_output_dir(cfg), "~/a")

    def test_add_destination_appends_labels_and_selects(self):
        first = str(Path(self.tmp.name) / "one")
        second = str(Path(self.tmp.name) / "two")
        config.add_destination(first)
        cfg, entry = config.add_destination(second, label="Chris Tucker")
        self.assertEqual(entry["label"], "Chris Tucker")
        self.assertEqual(cfg["destination_id"], entry["id"])
        self.assertEqual([d["path"] for d in config.destinations(cfg)],
                         [first, second])

    def test_add_destination_defaults_label_to_folder_name(self):
        cfg, entry = config.add_destination(str(Path(self.tmp.name) / "Videos"))
        self.assertEqual(entry["label"], "Videos")

    def test_ids_are_unique(self):
        config.add_destination(str(Path(self.tmp.name) / "one"))
        cfg, _ = config.add_destination(str(Path(self.tmp.name) / "two"))
        ids = [d["id"] for d in config.destinations(cfg)]
        self.assertEqual(len(ids), len(set(ids)))

    def test_select_destination_switches_the_effective_dir(self):
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        cfg, b = config.add_destination(str(Path(self.tmp.name) / "b"))
        cfg, err = config.select_destination(a["id"])
        self.assertEqual(err, "")
        self.assertEqual(config.effective_output_dir(cfg), a["path"])

    def test_select_unknown_destination_reports_an_error(self):
        cfg, err = config.select_destination("nope")
        self.assertNotEqual(err, "")

    def test_removing_the_selected_destination_falls_back_to_the_first(self):
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        cfg, b = config.add_destination(str(Path(self.tmp.name) / "b"))
        cfg, err = config.remove_destination(b["id"])
        self.assertEqual(err, "")
        self.assertEqual(cfg["destination_id"], a["id"])

    def test_removing_the_last_destination_leaves_no_selection(self):
        cfg, a = config.add_destination(str(Path(self.tmp.name) / "a"))
        cfg, err = config.remove_destination(a["id"])
        self.assertEqual(config.destinations(cfg), [])
        self.assertIsNone(config.selected_destination(cfg))

    def test_effective_output_dir_falls_back_to_the_default_when_empty(self):
        cfg = config.load()
        self.assertEqual(config.effective_output_dir(cfg),
                         config.DEFAULT_DESTINATION)


if __name__ == "__main__":
    unittest.main()
