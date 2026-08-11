import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from footagegrab.timefmt import fmt_clock, fmt_file, fmt_section, parse_time


class ParseTimeTests(unittest.TestCase):
    def test_plain_seconds(self):
        self.assertEqual(parse_time(78), 78.0)
        self.assertEqual(parse_time("78"), 78.0)
        self.assertEqual(parse_time("78.5"), 78.5)
        self.assertEqual(parse_time(0), 0.0)

    def test_clock_forms(self):
        self.assertEqual(parse_time("1:18"), 78.0)
        self.assertEqual(parse_time("01:02:03"), 3723.0)
        self.assertEqual(parse_time("01:02:03.5"), 3723.5)
        self.assertEqual(parse_time("0:05"), 5.0)

    def test_rejects_garbage(self):
        for bad in ("", "abc", "1:2:3:4", "1::2", "-5", "1:-2", None, True):
            with self.assertRaises((ValueError, AttributeError), msg=repr(bad)):
                parse_time(bad)


class FormatTests(unittest.TestCase):
    def test_fmt_clock(self):
        self.assertEqual(fmt_clock(78.4), "1:18")
        self.assertEqual(fmt_clock(5), "0:05")
        self.assertEqual(fmt_clock(3723), "1:02:03")
        self.assertEqual(fmt_clock(0), "0:00")

    def test_fmt_file_has_no_colons(self):
        self.assertEqual(fmt_file(78), "01.18")
        self.assertEqual(fmt_file(3723), "1.02.03")
        self.assertNotIn(":", fmt_file(363642))

    def test_fmt_section(self):
        self.assertEqual(fmt_section(42), "42")
        self.assertEqual(fmt_section(42.5), "42.5")
        self.assertEqual(fmt_section(42.55), "42.5")  # one decimal, floor-ish
        self.assertEqual(fmt_section(0), "0")


if __name__ == "__main__":
    unittest.main()
