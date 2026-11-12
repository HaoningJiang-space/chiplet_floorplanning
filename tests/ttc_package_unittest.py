from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.sparse.linalg import spsolve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from validation.ttc_package import Assembly, build, solve
from validation.ttc_separable import transfer
from ttc_separable_unittest import fixture


def boundary_fixture():
    return dict(baseLength=.006, baseWidth=.006, baseHeight=.001, baseCols=3,
                finHeight=.002, finThickness=.0005, k=401., rho=8960., cp=384.6,
                full_pad_side_m=.005, natural_htc_w_per_m2_k=2.8, fan_htc_w_per_m2_k=22.)


class TTCPackageTest(unittest.TestCase):
    def test_joined_materials_match_analytic_one_dimensional_resistance(self):
        graph = Assembly()
        a = graph.block('a', [0., .002, .005], [0., .003], [0., .001], 4., 1e6)
        b = graph.block('b', a.x, a.y, [.001, .004], 10., 2e6)
        graph.join(a, b)
        area = np.outer(np.diff(a.y), np.diff(a.x))
        graph.anchor(b.ids[-1], area/(.003/(2*10.)))
        g, loss, _, _ = graph.matrix()
        flux = 7000.
        rhs = np.zeros(graph.count); rhs[a.ids[0].ravel()] = (flux*area).ravel()
        t = spsolve(g, rhs)
        np.testing.assert_allclose(t[a.ids], flux*(.001/(2*4)+.003/10), atol=1e-12)
        np.testing.assert_allclose(t[b.ids], flux*.003/(2*10), atol=1e-12)
        self.assertAlmostEqual(loss @ t, rhs.sum(), places=12)

    def test_interface_affine_field_and_nonmatching_rejection(self):
        graph = Assembly()
        a = graph.block('a', [0., .001, .003], [0., .002, .005], [0., .001], 7., 1e6)
        b = graph.block('b', a.x, a.y, [.001, .004], 7., 1e6)
        graph.join(a, b)
        edge = graph.interfaces[0]
        temperatures = []
        for block in (a, b):
            z, y, x = np.meshgrid((block.z[:-1]+block.z[1:])/2,
                                  (block.y[:-1]+block.y[1:])/2,
                                  (block.x[:-1]+block.x[1:])/2, indexing='ij')
            temperatures.append((3*x+2*y+5*z).ravel())
        t = np.concatenate(temperatures)
        expected = -7*5*(a.x[-1]-a.x[0])*(a.y[-1]-a.y[0])
        self.assertAlmostEqual(edge['g'] @ (t[edge['a']]-t[edge['b']]), expected, places=12)
        bad = graph.block('bad', [0., .0015, .003], a.y, [.001, .004], 7., 1e6)
        with self.assertRaises(ValueError):
            graph.join(a, bad)

    def test_uniform_package_matches_separable_on_same_custom_axes(self):
        geometry = fixture()
        for level in (0, 1):
            g, loss, b, h, graph, audit = build(geometry, boundary_fixture(), 'heatsink', level, 'U')
            direct, _ = solve(g, loss, b, h, graph, method='direct')
            factor = 2**level
            separated, _ = transfer(geometry, 'heatsink', 1., active_cells=factor,
                bulk_cells=2*factor, pad_cells=2*factor, xy_edges=audit['die_xy_edges_m'])
            np.testing.assert_allclose(direct, separated-1., atol=1e-9, rtol=1e-10)

    def test_amg_matches_direct_and_source_port_reciprocity(self):
        g, loss, b, h, graph, audit = build(fixture(), boundary_fixture(), 'heatsink_with_fan', 0, 'P')
        direct, _ = solve(g, loss, b, h, graph, method='direct')
        iterative, result = solve(g, loss, b, h, graph)
        np.testing.assert_allclose(iterative, direct, atol=1e-7, rtol=1e-9)
        ports = np.asarray(b.T @ spsolve(g, b.toarray()))
        np.testing.assert_allclose(ports, ports.T, atol=1e-10, rtol=1e-11)
        self.assertGreater(ports.min(), 0.)
        self.assertEqual(audit['symmetry_error'], 0.)
        self.assertLess(max(r['boundary_heat_error_w'] for r in result['channels']), 1e-8)

    def test_fin_height_refinement_to_analytic_insulated_tip(self):
        k, thick, width, height, htc = 50., .0005, .04, .02, 20.
        effective_h = 1/(1/htc+thick/(2*k))
        m = np.sqrt(2*effective_h/(k*thick))
        exact = k*thick*width*m*np.tanh(m*height)
        errors = []
        for count in (8, 16, 32):
            graph = Assembly()
            fin = graph.block('fin', [0., thick], [0., width], np.linspace(0., height, count+1), k, 1e6)
            dz = height/count
            face_area = np.full((count, 1), dz*width)
            graph.anchor(fin.ids[:, :, 0], 2*effective_h*face_area)
            bottom_g = 2*k*thick*width/dz
            graph.anchor(fin.ids[0], bottom_g)
            g, _, _, _ = graph.matrix()
            rhs = np.zeros(graph.count); rhs[0] = bottom_g
            t = spsolve(g, rhs)
            admittance = bottom_g*(1-t[0])
            errors.append(abs(admittance-exact))
        self.assertGreater(errors[-2]/errors[-1], 3.9)
        self.assertLess(errors[-1]/exact, 1e-4)

    def test_actual_footprint_capacities_are_not_duplicated(self):
        geo, boundary = fixture(), boundary_fixture()
        _, _, _, _, _, a = build(geo, boundary, 'heatsink', 0, 'C')
        _, _, _, _, _, b = build(geo, boundary, 'heatsink', 0, 'P')
        pad_cv = geo['materials']['natural']['SILICONE'].get('volumetric_capacity_j_per_m3_k')
        expected = (boundary['full_pad_side_m']**2-(geo['die_side_um']*1e-6)**2)*geo['thermal_pad_um']*1e-6*pad_cv
        self.assertAlmostEqual(b['total_capacity_j_per_k']-a['total_capacity_j_per_k'], expected, places=12)
        self.assertAlmostEqual(b['interface_areas_m2']['die->pad'], (geo['die_side_um']*1e-6)**2, places=14)
        self.assertAlmostEqual(b['interface_areas_m2']['pad->base'], boundary['full_pad_side_m']**2, places=14)


if __name__ == '__main__':
    unittest.main()
