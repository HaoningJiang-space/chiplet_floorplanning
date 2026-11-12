from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from audit_integrated_transistors import build_fabric
from compare_hits_cpu import completion_status
from chiplet_floorplanning.network_sta import netlist
from chiplet_floorplanning.shared_parasitics import SPEF_HEADER, spef_tree


class TransistorFabricTest(unittest.TestCase):
    def fixture(self):
        text = netlist(4)
        models = {}
        for model, instance, ports in re.findall(r'(thermal_\w+)\s+(\w+)\s*\(([^;]+)\);', text):
            cell = 'dfxtp_1' if '.CLK' in ports else 'inv_1' if '.Y' in ports else 'buf_8'
            models[instance] = dict(cell=model, source_files={f'sky_{cell}_tt_025C_1v80.json': 'test'})
        mappings = {f'data_{g}_{l}': (f'data_{g}_{l}', f'data_cell_{g}_{l}:X', [f'rx_{g}_{l}:D']) for g in range(2) for l in range(4)}
        mappings['forwarded_clock'] = ('forwarded', 'clock_trunk:X', ['branch_0_cell:A', 'branch_1_cell:A'])
        rc = {}
        spef = SPEF_HEADER
        for key, (design, source, sinks) in mappings.items():
            n = len(sinks)+1
            r = dict(design_net=design, source_pin=source, sink_pins=sinks, nodes=list(range(n)),
                     source_index=0, sink_indices=list(range(1,n)), node_parasitic_pf=[.1]*n,
                     total_parasitic_pf=.1*n, total_sink_pin_pf=.7,
                     conductors=[dict(a=0,b=i,resistance_ohm=2.) for i in range(1,n)])
            rc[key] = r
            spef += spef_tree(design,source,sinks,r)
        return text, dict(models=models,rc=rc), spef

    def test_shared_wire_once_and_no_liberty_pin_cap_double_count(self):
        elements, nodes = build_fabric(*self.fixture())
        self.assertEqual(sum(e.startswith('R_') for e in elements), 10)
        self.assertEqual(sum(e.startswith('C_') for e in elements), 19)
        self.assertAlmostEqual(sum(float(e.split()[-1][:-1]) for e in elements if e.startswith('C_')), 1.9)
        self.assertEqual(nodes['clock_trunk:X'], 'wire_forwarded_clock_0')
        self.assertEqual(nodes['branch_1_cell:A'], 'wire_forwarded_clock_2')
        self.assertEqual(sum(e.startswith('X_') for e in elements), 32)

    def test_missing_cell_and_wrong_source_identity_rejected(self):
        text, receipt, spef = self.fixture()
        with self.assertRaises(ValueError):
            build_fabric(text.replace('thermal_clock_root clock_root (.A(clk), .X(common));',''), receipt,spef)
        receipt['models']['clock_root']['source_files'] = {'sky_inv_1_tt_025C_1v80.json':'test'}
        with self.assertRaisesRegex(ValueError,'identity'):
            build_fabric(text,receipt,spef)

    def test_missing_data_or_clock_rc_rejected(self):
        for missing in ('data_0_0','forwarded_clock'):
            text,receipt,spef = self.fixture()
            del receipt['rc'][missing]
            with self.assertRaisesRegex(ValueError,'nine-net'):
                build_fabric(text,receipt,spef)

    def test_nonpassive_conductor_rejected(self):
        text,receipt,spef = self.fixture()
        receipt['rc']['data_0_0']['conductors'][0]['resistance_ohm'] = 0
        with self.assertRaisesRegex(ValueError,'resistance'):
            build_fabric(text,receipt,spef)

    def test_changed_rc_and_terminal_rejected(self):
        text,receipt,spef = self.fixture()
        receipt['rc']['data_0_0']['node_parasitic_pf'][0] *= 2
        with self.assertRaisesRegex(ValueError,'SPEF'):
            build_fabric(text,receipt,spef)
        text,receipt,spef = self.fixture()
        receipt['rc']['data_0_0']['sink_pins'] = ['rx_1_0:D']
        with self.assertRaisesRegex(ValueError,'mapping'):
            build_fabric(text,receipt,spef)

    def test_hits_rejection_is_not_success(self):
        cases = [dict(profile='a',receipt=dict(accepted=True)),dict(profile='b',receipt=dict(accepted=False))]
        status = completion_status(cases,['a','b'])
        self.assertTrue(status['execution_complete'])
        self.assertFalse(status['complete'])
        self.assertFalse(status['all_solvers_accepted'])
        self.assertFalse(completion_status(cases[:1],['a','b'])['execution_complete'])
        cases[1]['receipt']['accepted'] = True
        self.assertTrue(completion_status(cases,['a','b'])['complete'])


if __name__ == '__main__':
    unittest.main()
