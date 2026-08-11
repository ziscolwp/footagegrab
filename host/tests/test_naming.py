import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab.naming import render_template, slugify, unique_path


class SlugifyTests(unittest.TestCase):
    def test_forbidden_characters_become_underscores(self):
        self.assertEqual(slugify('Oprah: The "Lost" Interview / Part 2'),
                         "Oprah_The_Lost_Interview_Part_2".replace('"', ""))
        for ch in '/\\:*?"<>|':
            self.assertNotIn(ch, slugify(f"a{ch}b"))

    def test_unicode_kept_control_stripped(self):
        self.assertEqual(slugify("Beyoncé — Live"), "Beyoncé_—_Live")
        self.assertEqual(slugify("a\x00\x1fb"), "a_b")

    def test_length_cap_and_fallback(self):
        self.assertLessEqual(len(slugify("x" * 500)), 64)
        self.assertEqual(slugify(""), "clip")
        self.assertEqual(slugify("   ...   "), "clip")


class TemplateTests(unittest.TestCase):
    FIELDS = {"title": "Oprah_Interview", "id": "dQw4w9WgXcQ",
              "start": "00.42", "end": "01.18", "date": "2026-08-11"}

    def test_segment_template(self):
        name = render_template("{title}_{start}-{end}_{id}", self.FIELDS)
        self.assertEqual(name, "Oprah_Interview_00.42-01.18_dQw4w9WgXcQ")

    def test_unknown_tokens_vanish(self):
        self.assertEqual(render_template("{title}_{nope}_{id}", self.FIELDS),
                         "Oprah_Interview_dQw4w9WgXcQ")

    def test_malformed_template_still_yields_name(self):
        self.assertTrue(render_template("{title", self.FIELDS))

    def test_empty_result_falls_back(self):
        self.assertEqual(render_template("{nope}", self.FIELDS), "clip")


class UniquePathTests(unittest.TestCase):
    def test_collisions_get_numeric_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            first = unique_path(d, "clip")
            self.assertEqual(first.name, "clip.mp4")
            first.touch()
            second = unique_path(d, "clip")
            self.assertEqual(second.name, "clip_2.mp4")
            second.touch()
            self.assertEqual(unique_path(d, "clip").name, "clip_3.mp4")


if __name__ == "__main__":
    unittest.main()
