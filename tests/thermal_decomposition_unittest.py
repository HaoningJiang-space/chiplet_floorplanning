import copy
import itertools
import unittest

import numpy as np

from chiplet_floorplanning.model import load_case, parse_case
from chiplet_floorplanning.thermal_decomposition import decompose_sources
from tools.validation.factorial import factorial_decomposition


class SourceDecompositionTests(unittest.TestCase):
    def case(self, powers=(0.001, 0.002)):
        raw = copy.deepcopy(load_case("examples/layered_two_chiplets.json").input_data)
        raw.update(package_mm=dict(width=2, height=1), grid=dict(nx=2, ny=1), links=[])
        raw["chiplets"] = [
            dict(
                id=name,
                size_mm=dict(width=1, height=1),
                placement_mm=dict(x=i, y=0),
                rotation_deg=0,
                ports_mm={},
                blocks=[
                    dict(
                        id="heat",
                        rect_mm=dict(x=0, y=0, width=1, height=1),
                        power_w=powers[i],
                        provenance="analytic two-node control",
                    )
                ],
            )
            for i, name in enumerate(("a", "b"))
        ]
        raw["thermal"].update(
            top_h_w_m2k=1000,
            bottom_h_w_m2k=0,
            power_layer="dies",
            layers=[
                dict(
                    id="dies",
                    footprint="chiplets",
                    thickness_mm=0.1,
                    conductivity_w_mk=100,
                    sidewall_contacts=[dict(dies=["a", "b"], resistance_m2k_w=0)],
                )
            ],
        )
        return parse_case(raw)

    def test_analytic_independent_sources_at_same_hotspot(self):
        report, grids = decompose_sources(self.case())
        sink = 1e-6 / (0.0001 / 200 + 1 / 1000)
        coupling = 100 * 1e-7 / 0.001
        determinant = sink * (sink + 2 * coupling)
        a = 0.001 * np.array([[sink + coupling, coupling]]) / determinant
        b = 0.002 * np.array([[coupling, sink + coupling]]) / determinant
        np.testing.assert_allclose(grids["a"], a, rtol=0, atol=1e-12)
        np.testing.assert_allclose(grids["b"], b, rtol=0, atol=1e-12)
        np.testing.assert_allclose(grids["total"], a + b, rtol=0, atol=1e-12)
        hot = report["total_hotspot"]
        self.assertEqual(hot["die_id"], "b")
        self.assertAlmostEqual(hot["temperature_c"], 25 + a[0, 1] + b[0, 1])
        self.assertGreater(
            sum(report["independent_source_peak_rises_k"].values()), hot["total_rise_k"]
        )
        self.assertTrue(report["all_source_matrices_identical"])

    def test_zero_power_die_remains_and_ambient_is_not_added_twice(self):
        base, _ = decompose_sources(self.case())
        one, grids = decompose_sources(self.case((0.001, 0)))
        self.assertEqual(base["matrix_sha256"], one["matrix_sha256"])
        self.assertEqual(one["material_node_count"], 2)
        self.assertGreater(grids["a"][0, 1], 0)
        self.assertEqual(
            one["total_hotspot"]["source_pattern_response_k_per_w"]["b"], None
        )
        zero, _ = decompose_sources(self.case((0, 0)))
        self.assertEqual(zero["total_hotspot"]["temperature_c"], 25)

    def test_rejects_different_model(self):
        with self.assertRaises(ValueError):
            decompose_sources(load_case("examples/two_chiplets.json"))


class FactorialTests(unittest.TestCase):
    def test_known_additive_and_interaction_variance(self):
        coordinates = list(itertools.product((-1, 0, 1), repeat=3))
        values = [2 * x + 3 * y + 4 * z + 5 * x * y for x, y, z in coordinates]
        r = factorial_decomposition(coordinates, values, ("x", "y", "z"))
        for term, ss in (("x", 72), ("y", 162), ("z", 288), ("x:y", 300)):
            self.assertAlmostEqual(r["terms"][term]["sum_squares_k2"], ss)
        self.assertAlmostEqual(r["total_sum_squares_k2"], 822)
        self.assertLess(r["sum_squares_closure_error_k2"], 1e-10)

    def test_incomplete_duplicate_and_constant_cases(self):
        coordinates = list(itertools.product((0, 1), repeat=2))
        for invalid in (coordinates[:-1], coordinates + [coordinates[0]]):
            with self.assertRaises(ValueError):
                factorial_decomposition(invalid, range(len(invalid)), ("x", "y"))
        r = factorial_decomposition(coordinates, [1] * 4, ("x", "y"))
        self.assertIsNone(r["main_effect_fraction"])
