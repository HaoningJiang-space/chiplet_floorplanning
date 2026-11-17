from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from atplace_train_retry import with_redraws  # noqa: E402


class RedrawTest(unittest.TestCase):
    def test_failed_draws_are_redrawn_then_the_last_error_is_raised(self):
        calls = []

        def sample(system, params, rng):
            calls.append(rng)
            if len(calls) < 3:
                raise RuntimeError('no legal layout')
            return 'layout'

        self.assertEqual(with_redraws(sample, 5)(None, None, 'rng'), 'layout')
        self.assertEqual(len(calls), 3)
        calls.clear()
        with self.assertRaises(RuntimeError):
            with_redraws(sample, 2)(None, None, 'rng')
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
