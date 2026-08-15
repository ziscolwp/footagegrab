import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab import system


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
