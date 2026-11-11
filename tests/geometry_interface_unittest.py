import copy
from pathlib import Path
import unittest

import numpy as np

from chiplet_floorplanning.characterization import sample_instance_temperature
from chiplet_floorplanning.liberty_checks import groups, lookup, read_table
from chiplet_floorplanning.interconnect import estimate_links
from chiplet_floorplanning.model import load_case, parse_case, ModelError
from chiplet_floorplanning.package import assemble_package, solve_package
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.timing import parse_sta_log

ROOT = Path(__file__).resolve().parents[1]


class ConformalGeometryTests(unittest.TestCase):
    def raw(self):
        return copy.deepcopy(load_case(ROOT/'examples/layered_two_chiplets.json').input_data)

    def test_nonuniform_material_area_energy_and_reciprocity(self):
        for angle in (0, 90, 180, 270):
            raw = self.raw()
            raw['chiplets'][0]['rotation_deg'] = angle
            raw['chiplets'][0]['placement_mm'] = {'x': 1.137, 'y': 2.219}
            case = parse_case(raw)
            power, _ = rasterize(case)
            matrix, _, _, _, ids, z = assemble_package(case, power)
            self.assertEqual(case.dies[0].x, 1.137)
            self.assertEqual(case.dies[0].y, 2.219)
            self.assertAlmostEqual(case.mesh.areas_mm2.sum(), 96)
            self.assertAlmostEqual(case.mesh.areas_mm2[ids[z] >= 0].sum(), 12)
            self.assertAlmostEqual(power.sum(), 3)
            self.assertEqual((matrix-matrix.T).nnz, 0)
            _, summary = solve_package(case, power)
            self.assertLess(abs(summary['energy_balance_error_w']), 3e-8)

    def test_anisotropic_contact_resistance_analytic_column(self):
        raw = self.raw()
        raw['chiplets'][0]['placement_mm']['x'] += 0.137
        cfg = raw['thermal']
        cfg['power_layer'] = cfg['layers'][0]['id']
        resistance_area = 1/cfg['top_h_w_m2k']
        for i, layer in enumerate(cfg['layers']):
            kz = layer.pop('conductivity_w_mk')
            layer['conductivity_xyz_w_mk'] = [2*kz, 0.5*kz, kz]
            layer['footprint'] = 'package'
            resistance_area += layer['thickness_mm']*1e-3/kz*(0.5 if i == 0 else 1)
            if i < len(cfg['layers'])-1:
                layer['contact_resistance_above_m2k_w'] = (i+1)*1e-5
                resistance_area += (i+1)*1e-5
        case = parse_case(raw)
        power = 3*case.mesh.areas_mm2/96
        temperature, _ = solve_package(case, power)
        np.testing.assert_allclose(temperature, 25+3*resistance_area/96e-6, rtol=0, atol=1e-7)

    def test_affine_temperature_reconstruction_and_void_isolation(self):
        for angle in (0, 90, 180, 270):
            raw = self.raw()
            raw['chiplets'][0]['rotation_deg'] = angle
            raw['chiplets'][0]['placement_mm']['x'] += 0.137
            case = parse_case(raw)
            xs, ys = np.meshgrid(case.mesh.x_centers_mm, case.mesh.y_centers_mm)
            grid = 30+2*xs+3*ys
            die = case.dies[0]
            r = die.bounds
            grid[(xs < r.x) | (xs > r.x+r.width) | (ys < r.y) | (ys > r.y+r.height)] = np.nan
            point = [1.17, 0.83]
            x, y = die.point(*point)
            value, record = sample_instance_temperature(case, grid, 'tx', point)
            self.assertAlmostEqual(value, 30+2*x+3*y)
            self.assertEqual(record['clamped_xy'], [False, False])
            self.assertAlmostEqual(sum(s['weight'] for s in record['samples']), 1)
            edge_value, edge_record = sample_instance_temperature(case, grid, 'tx', [0, 0])
            self.assertTrue(np.isfinite(edge_value))
            self.assertTrue(any(edge_record['clamped_xy']))

    def test_unequal_cells_anisotropic_lateral_analytic_network(self):
        for vertical, coupling in ((False, 1/750), (True, 1/3000)):
            raw = self.raw()
            raw['package_mm'] = {'width': 1 if vertical else 3, 'height': 3 if vertical else 1}
            raw['grid'] = {'nx': 1, 'ny': 1}
            raw['links'] = []
            raw['chiplets'] = []
            for i, (offset, extent) in enumerate(((0, 1), (1, 2))):
                width, height = (1, extent) if vertical else (extent, 1)
                raw['chiplets'].append({'id': f'die{i}', 'size_mm': {'width': width, 'height': height},
                    'placement_mm': {'x': 0 if vertical else offset, 'y': offset if vertical else 0},
                    'rotation_deg': 0, 'ports_mm': {}, 'blocks': [{'id': 'source',
                    'rect_mm': {'x': 0, 'y': 0, 'width': width, 'height': height},
                    'power_w': 0.001 if i == 0 else 0, 'provenance': 'analytic two-node control'}]})
            raw['thermal']['layers'] = [{'id': 'plate', 'footprint': 'package', 'thickness_mm': 0.1,
                                         'conductivity_xyz_w_mk': [20, 5, 100]}]
            raw['thermal']['power_layer'] = 'plate'
            case = parse_case(raw)
            power, _ = rasterize(case)
            temperature, _ = solve_package(case, power)
            # Area ratio 1:2; half thickness / kz plus top convection in series.
            sink1, sink2 = 1e-6/0.0010005, 2e-6/0.0010005
            determinant = sink1*sink2+coupling*(sink1+sink2)
            expected = 25+0.001*np.array([sink2+coupling, coupling])/determinant
            np.testing.assert_allclose(temperature.ravel(), expected, rtol=0, atol=1e-10)

    def test_material_contract_rejects_ambiguous_or_invalid_values(self):
        for change in ({'conductivity_xyz_w_mk': [1, 2, 3]},
                       {'contact_resistance_above_m2k_w': -1}):
            raw = self.raw()
            raw['thermal']['layers'][0].update(change)
            with self.assertRaises(ModelError):
                parse_case(raw)
        raw = self.raw()
        raw['thermal']['layers'][-1]['contact_resistance_above_m2k_w'] = 1e-5
        with self.assertRaises(ModelError):
            parse_case(raw)

    def test_explicit_route_length_and_stale_endpoint_rejection(self):
        raw = self.raw()
        raw['links'][0]['route_points_mm'] = [[4, 2.6], [4.5, 2.6], [4.5, 1.6], [6.5, 1.6], [6.5, 2.6], [7, 2.6]]
        link = estimate_links(parse_case(raw))[0]
        self.assertAlmostEqual(link['manhattan_length_mm'], 3)
        self.assertAlmostEqual(link['modeled_length_mm'], 5)
        self.assertAlmostEqual(link['assumed_r_ohm'], 5*1.68)
        raw['chiplets'][0]['placement_mm']['x'] += 0.1
        with self.assertRaisesRegex(ModelError, 'reroute'):
            parse_case(raw)


class InterfaceEvidenceTests(unittest.TestCase):
    def test_table_lookup_independent_bilinear_and_outside_domain(self):
        text = 'cell_rise(t) { index_1("1, 3"); index_2("2, 4"); values("5, 7", "9, 11"); }'
        table = read_table(text, 'cell_rise')
        self.assertAlmostEqual(lookup(table, [2, 3]), 8)
        for point in ([0, 3], [2, 5], [float('nan'), 3]):
            with self.assertRaises(ValueError):
                lookup(table, point)
        self.assertEqual(list(groups('pin("A") { function : "{A}"; }', 'pin')),
                         [('A', ' function : "{A}"; ')])

    def test_all_reported_wire_capacitance_variants_checked(self):
        links = [{'kind': k, 'assumed_c_pf': 0.01} for k in ('data', 'clock')]
        log = ('Wire capacitance: r 0.01:0.01 f 0.01:0.01\nWire capacitance: 0.01\n'
               'LANE_SLACK_max 1\nLANE_SLACK_min 2\n')
        self.assertEqual(len(parse_sta_log(log, links)[1]), 2)
        with self.assertRaises(ValueError):
            parse_sta_log(log.replace('f 0.01:0.01', 'f 0.01:0.02'), links)

    def test_short_wire_float32_cancellation_bound_is_not_missing_annotation(self):
        links = [{'kind': k, 'assumed_c_pf': 0.00345313324699} for k in ('data', 'clock')]
        log = ('Wire capacitance: 0.003452967\nTotal capacitance: 4.098484039\n')*2
        log += 'LANE_SLACK_max 1\nLANE_SLACK_min 2\n'
        self.assertEqual(len(parse_sta_log(log, links)[1]), 2)
        with self.assertRaises(ValueError):
            parse_sta_log(log.replace('0.003452967', '0.000000000'), links)


if __name__ == '__main__':
    unittest.main()
