from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.sparse.linalg import spsolve

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from validation.ttc_separable import lateral, vertical, configuration, planar_mappings, transfer
from validation.ttc_spatial import stack, weights
from validation.ttc_spectral import impedance


def fixture():
    material = {'SILICON': {'conductivity_w_per_m_k': 70.},
                'SILICONE': {'conductivity_w_per_m_k': 5.}}
    heaters, sensors = [], []
    for channel in range(16):
        x, y = (channel % 4)*1000, (channel//4)*1000
        sensors.append([x+500, y+500])
        for offset in (110, 610):
            heaters.append(dict(power_index=channel, power_fraction=.5, x_um=x+120,
                                y_um=y+offset, width_um=760, height_um=280))
    return dict(die_side_um=4000., active_silicon_um=40., bulk_silicon_um=500.,
                thermal_pad_um=300., heaters=heaters, sensors_xy_um=sensors,
                materials={'natural': material, 'fan': material})


class TTCSeparableTest(unittest.TestCase):
    def test_nonuniform_all_nodes_match_independent_3d_assembly(self):
        x = np.array([0., .0003, .001, .002])
        y = np.array([0., .0004, .0015])
        dz, k, source = np.array([.0001, .0004, .0007]), np.array([70., 4., 12.]), np.array([.6, .4, 0.])
        ga = .7
        g, _, _ = stack(x, y, dz, k, np.full(3, 1e6), ga, 3.)
        planar = np.array([[.1, .2, .3], [.7, 1.1, 2.]])
        b = np.r_[(source[:, None, None]*planar).ravel(), 0.]
        direct = spsolve(g, b)
        lx, vx, _ = lateral(x)
        ly, vy, _ = lateral(y)
        z, audit = vertical((ly[:, None]+lx[None, :]).ravel(), dz, k, source)
        modal_source = vy.T @ planar @ vx
        fields = np.array([vy @ (layer.reshape(planar.shape)*modal_source) @ vx.T for layer in z])
        predicted = np.r_[fields.ravel()+planar.sum()/ga, planar.sum()/ga]
        np.testing.assert_allclose(predicted, direct, atol=1e-10, rtol=1e-11)
        np.testing.assert_allclose(g @ predicted, b, atol=2e-12, rtol=0)
        self.assertLess(audit['max_vertical_backward_error'], 1e-13)
        self.assertAlmostEqual(ga*predicted[-1], b.sum(), places=12)

    def test_source_and_point_mapping_match_sparse_sensor_solution(self):
        geometry = fixture()
        for subdivisions in ((1, 2, 2), (2, 3, 4)):
            x, y, dz, k, source = configuration(geometry, 'heatsink', 700., *subdivisions)
            g, _, _ = stack(x, y, dz, k, np.full(len(dz), 1e6), .6, 2.)
            planar_b, planar_h = planar_mappings(geometry, x, y)
            b = np.vstack(((source[:, None, None, None]*planar_b).reshape(-1, 16), np.zeros((1, 16))))
            h = np.zeros((16, len(dz), len(y)-1, len(x)-1))
            for z, weight in weights(np.cumsum(dz)-dz/2, geometry['active_silicon_um']*1e-6/2):
                h[:, z] = weight*planar_h
            h = np.column_stack((h.reshape(16, -1), np.zeros(16)))
            direct = h @ spsolve(g, b)
            result, audit = transfer(geometry, 'heatsink', .6, 700., *subdivisions)
            np.testing.assert_allclose(result, direct, atol=2e-10, rtol=1e-11)
            self.assertLess(audit['zero_mode_heat_balance_error'], 1e-10)
            self.assertLess(audit['constant_source_projection_error'], 1e-12)

    def test_depth_convergence_for_independent_continuum_modes(self):
        q = np.array([0., 400., 4000., 20000.])
        a, bulk, pad, ks, kp = .00004, .0005, .0003, 70., 5.
        exact = impedance(q, a, bulk, pad, ks, kp)
        errors = []
        for n in (2, 4, 8, 16, 32):
            dz = np.r_[np.full(n, a/n), np.full(2*n, bulk/(2*n)), np.full(2*n, pad/(2*n))]
            k = np.r_[np.full(3*n, ks), np.full(2*n, kp)]
            src = np.r_[np.full(n, 1/n), np.zeros(4*n)]
            z, _ = vertical(q*q, dz, k, src)
            observed = sum(w*z[i] for i, w in weights(np.cumsum(dz)-dz/2, a/2))
            errors.append(abs(observed-exact))
        errors = np.array(errors)
        # Midpoint interpolation cancels the quadratic zero-mode truncation for
        # even active subdivisions; nonzero modes approach the continuum.
        self.assertLess(errors[:, 0].max(), 1e-14)
        self.assertTrue(np.all(errors[-1, 1:] < errors[0, 1:]/100))
        self.assertTrue(np.all(errors[-2, 1:]/errors[-1, 1:] > 3.8))

    def test_full_plane_constant_mode_and_bath_shift(self):
        geometry = fixture()
        geometry['heaters'] = [dict(power_index=i, power_fraction=1., x_um=0., y_um=0.,
                                    width_um=4000., height_um=4000.) for i in range(16)]
        first, _ = transfer(geometry, 'heatsink', .5, 250., 2, 4, 4)
        second, _ = transfer(geometry, 'heatsink', 2., 250., 2, 4, 4)
        exact = impedance(np.array([0.]), 40e-6, 500e-6, 300e-6, 70., 5.)[0]/.004**2 + 2.
        np.testing.assert_allclose(first, exact, atol=1e-11, rtol=0)
        np.testing.assert_allclose(first-second, 1.5, atol=1e-11, rtol=0)

    def test_invalid_geometry_and_nonpassive_stack_rejected(self):
        for edges in ([0., 0.], [1., 0.], [0., np.nan]):
            with self.assertRaises(ValueError):
                lateral(edges)
        with self.assertRaises(ValueError):
            vertical([0., -1.], [.1], [1.], [1.])
        with self.assertRaises(ValueError):
            vertical([0.], [.1], [0.], [1.])
        with self.assertRaises(ValueError):
            vertical([0.], [.1], [1.], [.5])


if __name__ == '__main__':
    unittest.main()
