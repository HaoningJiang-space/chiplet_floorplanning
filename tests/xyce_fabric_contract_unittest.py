import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from validation.xyce_fabric_contract import verify_hot_deck, hot_model_root


class FullHotDeckTest(unittest.TestCase):
    def setUp(self):
        self.output = Path('results/contract-test-only')
        cells = ['buf_8.spice', 'inv_1.spice', 'dfxtp_1.spice']
        controls = ['.options device temp=25', 'VDD vdd 0 1.8',
                    'VCLK clk 0 PWL(0 0 1n 1.8)', '.tran 2.5p 60n 0 2.5p',
                    '.print tran format=csv V(clk)']
        self.elements = ['R_a a b 2', 'X_buf a b vdd 0 buf_8 cell_temp_c=65']
        self.cold = '\n'.join(['test', '.lib "original/sky130.lib.spice" tt',
            *[f'.include "original/{c}"' for c in cells], *controls, 'R_a a b 1',
            'X_buf a b vdd 0 buf_8', '.end'])+'\n'
        self.hot = '\n'.join(['test',
            f'.lib "{(hot_model_root(self.output)/"libs.tech/ngspice/sky130.lib.spice").as_posix()}" tt',
            *[f'.include "{(self.output/c).resolve().as_posix()}"' for c in cells],
            *controls, *self.elements, '.end'])+'\n'

    def test_only_declared_export_changes_admitted(self):
        verify_hot_deck(self.cold, self.hot, self.elements, self.output)

    def test_changed_stimulus_supply_controls_or_include_rejected(self):
        mutations = [('VDD vdd 0 1.8', 'VDD vdd 0 1.7'),
                     ('1n 1.8', '2n 1.8'), ('temp=25', 'temp=65'),
                     ('.tran 2.5p', '.tran 5p'), ('buf_8.spice', 'other.spice'),
                     ('sky130.lib.spice', 'other.lib.spice'), ('" tt', '" ff')]
        for old, new in mutations:
            with self.subTest(change=new), self.assertRaises(ValueError):
                verify_hot_deck(self.cold, self.hot.replace(old, new), self.elements, self.output)

    def test_extra_directive_and_missing_cell_rejected(self):
        with self.assertRaises(ValueError):
            verify_hot_deck(self.cold, self.hot.replace('.end', '.options device temp=90\n.end'), self.elements, self.output)
        with self.assertRaises(ValueError):
            verify_hot_deck(self.cold.replace('.include "original/inv_1.spice"\n', ''), self.hot, self.elements, self.output)


if __name__ == '__main__':
    unittest.main()
