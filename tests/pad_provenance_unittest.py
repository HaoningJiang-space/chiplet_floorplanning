import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from validation.pad_provenance import canonical_blocks, replace_definitions, renamed_library_equal


class PadProvenanceTest(unittest.TestCase):
    def test_only_selected_definition_changes(self):
        base = '* license\n.SUBCKT a x y\n.param gain=1\nR1 x y 10\n.ENDS a\n\n.SUBCKT b x y\nC1 x y 2p\n.ENDS\n'
        ref = base.replace('gain=1', 'gain=2').replace('2p', '3p')
        result = replace_definitions(base, ref, ['a'])
        self.assertEqual(result, base.replace('gain=1', 'gain=2'))
        self.assertNotEqual(canonical_blocks(base)['a'], canonical_blocks(result)['a'])

    def test_pin_permutation_rejected(self):
        base = '.subckt a x y\nR1 x y 10\n.ends\n'
        with self.assertRaisesRegex(ValueError, 'port order'):
            replace_definitions(base, base.replace('a x y', 'a y x'), ['a'])

    def test_missing_duplicate_and_nested_rejected(self):
        base = '.subckt a x y\nR1 x y 10\n.ends\n'
        for names in ([], ['b'], ['a', 'a']):
            with self.assertRaises(ValueError):
                replace_definitions(base, base, names)
        with self.assertRaises(ValueError):
            canonical_blocks(base + base)
        with self.assertRaises(ValueError):
            canonical_blocks('.subckt a x\n.subckt b y\n.ends\n.ends\n')

    def test_rename_does_not_hide_numeric_change(self):
        ref = 'library(old) {cell(old) {capacitance: 1.2;}}'
        self.assertTrue(renamed_library_equal(ref, ref.replace('old', 'new'), 'old', 'new'))
        self.assertFalse(renamed_library_equal(ref, ref.replace('old', 'new').replace('1.2', '1.3'), 'old', 'new'))


if __name__ == '__main__':
    unittest.main()
