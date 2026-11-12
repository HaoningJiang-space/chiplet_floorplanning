from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.linalg import expm
from scipy.sparse import csr_matrix, diags
from scipy.sparse.linalg import spsolve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from validation.ttc_reduction import body_basis, snapshot_bank, project, SHIFTS, frequency_reference, backward_euler_pulse


def network(count=36):
    conductance = .3
    diagonal = np.full(count, 2*conductance)
    diagonal[0] = conductance
    diagonal[-1] = conductance+.1
    g = diags((-np.full(count-1, conductance), diagonal, -np.full(count-1, conductance)), (-1, 0, 1)).tocsr()
    c = np.linspace(.01, .03, count)
    b = np.zeros((count, 2)); b[0, 0] = 1.; b[count//2, 1] = 1.
    h = np.eye(count)[[0, count//3, count-1]]
    groups = np.array_split(np.arange(count), 3)
    loss = np.asarray(g.sum(axis=0)).ravel()
    return g, c, csr_matrix(b), csr_matrix(h), loss, groups


class TTCReductionTest(unittest.TestCase):
    def test_mandatory_body_partition_is_mass_orthonormal(self):
        c = np.array([1., 2., 3., 4.])
        groups = [np.array([0, 1]), np.array([2, 3])]
        q = body_basis(c, groups)
        np.testing.assert_allclose(q.T @ q, np.eye(2), atol=1e-14)
        np.testing.assert_allclose(q @ (q.T @ np.sqrt(c)), np.sqrt(c), atol=1e-14)
        with self.assertRaises(ValueError):
            body_basis(c, [[0, 1], [1, 2, 3]])

    def test_partial_projection_keeps_dc_and_each_body_heat_balance(self):
        g, c, b, h, loss, groups = network()
        bank, _ = snapshot_bank(g, c, b, SHIFTS[0])
        r = project(g, c, b, h, loss, groups, bank, SHIFTS[0])
        self.assertLess(len(r.rates), len(c))
        np.testing.assert_allclose(r.frequency(0).real, h @ spsolve(g, b.toarray()), atol=1e-9)
        power = np.array([[1., 0.], [0., 3.], [2., 1.], [0., 0.]])
        initial = r.initial(power, [4., 6., 8.])
        self.assertAlmostEqual((r.sensors @ initial).mean(), 6., places=10)
        _, ledger, physical = r.run(power, initial, chunk_size=3)
        self.assertTrue(ledger['numerical_heat_balance_screen'])
        self.assertLess(ledger['max_body_interval_error_j'], 1e-10)
        np.testing.assert_allclose(physical['body_storage_rate_w'].sum(axis=1)+physical['boundary_loss_w'], power.sum(axis=1), atol=1e-9)

    def test_full_span_matches_independent_matrix_exponential(self):
        g, c, b, h, loss, _ = network(9)
        groups = [np.array([i]) for i in range(9)]
        bank, _ = snapshot_bank(g, c, b, SHIFTS[0])
        r = project(g, c, b, h, loss, groups, bank, SHIFTS[0])
        power = np.array([[1., 0.], [0., 3.], [2., 1.], [0., 0.]])
        initial = r.initial(power, [4., 6., 8.], uniform=True)
        actual, _, _ = r.run(power, initial, chunk_size=1)
        augmented = np.zeros((11, 11))
        augmented[:9, :9] = -g.toarray()/c[:, None]
        augmented[:9, 9:] = b.toarray()/c[:, None]
        transition = expm(.1*augmented)
        state = np.full(9, 6.); expected = []
        for p in power:
            state = (transition @ np.r_[state, p])[:9]
            expected.append(h @ state)
        np.testing.assert_allclose(actual, expected, atol=2e-11, rtol=0)

    def test_nested_snapshots_reduce_unseen_frequency_error(self):
        g, c, b, h, loss, groups = network()
        bank, _ = snapshot_bank(g, c, b)
        reference = frequency_reference(g, c, b, h, (.03, .3, 3., 30.))
        errors = []
        for shifts in SHIFTS:
            r = project(g, c, b, h, loss, groups, bank, shifts)
            errors.append(max(float(abs(r.frequency(w)-value).max()) for w, value in reference.items()))
        self.assertLess(errors[-1], errors[0]/100)
        self.assertLess(errors[-1], 1e-3)

    def test_independent_pulse_time_refinement(self):
        g, c, b, h, loss, _ = network(9)
        bank, _ = snapshot_bank(g, c, b, SHIFTS[0])
        r = project(g, c, b, h, loss, [np.array([i]) for i in range(9)], bank, SHIFTS[0])
        power = np.array([[2.], [1.]])
        trace = np.r_[np.repeat(power.T, 5, axis=0), np.full((5, 2), .2)]
        initial = (np.array([.2, .2]) @ r.inputs)/r.rates
        exact, _, _ = r.run(trace, initial)
        be = [backward_euler_pulse(g, c, b, h, power, dt)[:, :, 0] for dt in (.01, .005, .0025)]
        first, second = 2*be[1]-be[0], 2*be[2]-be[1]
        self.assertLess(abs(second-exact).max(), abs(first-exact).max()/3)


if __name__ == '__main__':
    unittest.main()
