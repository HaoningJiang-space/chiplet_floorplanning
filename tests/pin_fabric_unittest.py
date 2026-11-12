import copy
import json
from pathlib import Path
import unittest

from chiplet_floorplanning.layout import relocate_design
from chiplet_floorplanning.model import Die, parse_case
from chiplet_floorplanning.pin_fabric import pin_fabric
from chiplet_floorplanning.routing_graph import audit, route_greedy
from chiplet_floorplanning.shared_parasitics import tree_rc


class PinFabricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = json.loads((Path(__file__).resolve().parents[1]/'examples/three_chiplet_decision.json').read_text())

    def test_non_square_rotation_and_bounds(self):
        expected = {0: (10.25, 20.75, 3, 2), 90: (11.25, 20.25, 2, 3),
                    180: (12.75, 21.25, 3, 2), 270: (10.75, 22.75, 2, 3)}
        for angle, values in expected.items():
            die = Die('d', 3, 2, 10, 20, angle, (), {})
            self.assertEqual((*die.point(.25, .75), die.bounds.width, die.bounds.height), values)

    def test_rotation_invalidates_old_routes_and_maps_every_pin_role(self):
        case = parse_case(self.cfg['design'])
        fabric, nets, pins = pin_fabric(case, self.cfg['routing'])
        result = route_greedy(fabric, nets)
        self.assertEqual(result['status'], 'feasible')
        moved = relocate_design(case, {'tx': {'x': .5, 'y': 3., 'rotation_deg': 90}})
        ff, nn, pp = pin_fabric(moved, self.cfg['routing'])
        self.assertFalse(audit(ff, nn, result['routes'])['fabric_legal'])
        by_name = {(p['chiplet'], p['port']): p for p in pp}
        for original in pins:
            if original['chiplet']=='tx':
                x, y = original['local_point_mm']
                self.assertEqual(by_name[('tx', original['port'])]['package_point_mm'], [.5+2-y, 3+x])
        # Power pins reserve all signal layers; clock is one multi-sink net.
        for pin in pp:
            if pin['kind']=='power':
                self.assertTrue(all(not ff.allowed((*pin['node'][:2], z)) for z in range(ff.layers)))
        self.assertEqual(sum(n.kind=='clock' for n in nn), 1)
        self.assertEqual(len(nn[-1].sinks), 2)

    def test_invalid_landing_spacing_grid_and_connectivity(self):
        for mutation in ('outside', 'spacing', 'off_grid', 'missing_role', 'unconnected'):
            cfg = copy.deepcopy(self.cfg)
            tx = cfg['design']['chiplets'][0]
            if mutation=='outside':
                tx['ports_mm']['vdd']['x'] = 0.
            elif mutation=='spacing':
                tx['ports_mm']['vdd'] = tx['ports_mm']['vss'].copy()
            elif mutation=='off_grid':
                tx['placement_mm']['x'] += .01
            elif mutation=='missing_role':
                del cfg['routing']['pins']['tx']['vdd']
            else:
                cfg['design']['links'] = cfg['design']['links'][1:]
            with self.assertRaises(ValueError, msg=mutation):
                pin_fabric(parse_case(cfg['design']), cfg['routing'])

    def test_temperature_resistance_keeps_unique_capacitance_and_scales_moment(self):
        fabric, nets, _ = pin_fabric(parse_case(self.cfg['design']), self.cfg['routing'])
        routed = route_greedy(fabric, nets); net = nets[-1]; edges = routed['routes'][net.name]
        nominal = tree_rc(fabric, net, edges, sink_cap_pf=[.01, .02])
        warm = tree_rc(fabric, net, edges, sink_cap_pf=[.01, .02], resistance_factors={e: 1.2 for e in edges})
        self.assertEqual(nominal['total_parasitic_pf'], warm['total_parasitic_pf'])
        self.assertEqual(len(warm['conductors']), len(edges))
        for a, b in zip(nominal['first_moment_ns'], warm['first_moment_ns']):
            self.assertAlmostEqual(b, 1.2*a, places=12)
        shunted = tree_rc(fabric, net, edges, sink_cap_pf=[.01, .02], sink_shunt_pf=.025)
        self.assertEqual(shunted['total_sink_pin_pf'], nominal['total_sink_pin_pf'])
        self.assertAlmostEqual(shunted['total_parasitic_pf']-nominal['total_parasitic_pf'], .05)
        self.assertTrue(all(b>a for a, b in zip(nominal['first_moment_ns'], shunted['first_moment_ns'])))
        with self.assertRaises(ValueError):
            tree_rc(fabric, net, edges, resistance_factors={e: -1 for e in edges})


if __name__=='__main__':
    unittest.main()
