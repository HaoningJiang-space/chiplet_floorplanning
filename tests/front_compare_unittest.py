from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from front_compare import verdict  # noqa: E402


class FrontCompareTest(unittest.TestCase):
    def test_verdict_rules(self):
        rows = lambda wins, losses: {k: dict(outcome='ours' if k < wins else 'atplace' if k < wins + losses else 'tie')
                                     for k in range(10)}
        self.assertEqual(verdict(rows(4, 1)), ('improved', 4, 1))
        self.assertEqual(verdict(rows(5, 3)), ('worse', 5, 3))
        self.assertEqual(verdict(rows(3, 2))[0], 'no_clear_difference')


if __name__ == '__main__':
    unittest.main()
