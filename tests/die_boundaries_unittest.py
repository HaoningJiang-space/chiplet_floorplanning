import copy
from pathlib import Path
import unittest

import numpy as np

from chiplet_floorplanning.model import load_case, parse_case, ModelError
from chiplet_floorplanning.package import assemble_package, solve_package
from chiplet_floorplanning.power import rasterize


class DieBoundaryTests(unittest.TestCase):
    def raw(self, gap=0):
        raw = copy.deepcopy(
            load_case(
                Path(__file__).resolve().parents[1]
                / "examples/layered_two_chiplets.json"
            ).input_data
        )
        raw["grid"] = {"nx": 1, "ny": 1}
        raw["package_mm"] = {"width": 3 + gap, "height": 1}
        raw["links"] = []
        raw["chiplets"] = [
            {
                "id": name,
                "size_mm": {"width": 1, "height": 1},
                "placement_mm": {"x": x, "y": 0},
                "rotation_deg": 0,
                "ports_mm": {},
                "blocks": [
                    {
                        "id": "source",
                        "rect_mm": {"x": 0, "y": 0, "width": 1, "height": 1},
                        "power_w": power,
                        "provenance": "independent thermal column control",
                    }
                ],
            }
            for name, x, power in [("a", 0, 0.001), ("b", 1 + gap, 0)]
        ]
        raw["thermal"]["layers"] = [
            {
                "id": "dies",
                "footprint": "chiplets",
                "thickness_mm": 0.1,
                "conductivity_w_mk": 150,
                "die_materials": {"b": {"conductivity_w_mk": 15}},
            }
        ]
        return raw

    def test_independent_die_sidewalls_touching_small_gap_and_large_gap(self):
        for gap in (0, 1e-5, 1):
            case = parse_case(self.raw(gap))
            power, _ = rasterize(case)
            matrix, _, _, _, _, _ = assemble_package(case, power)
            self.assertEqual(matrix.shape, (2, 2))
            self.assertEqual(matrix[0, 1], 0)
            temperature, _ = solve_package(case, power)
            solid = temperature[np.isfinite(temperature)]
            np.testing.assert_allclose(
                solid, [25 + 0.001 * (1000 + 1 / 3), 25], rtol=0, atol=1e-10
            )

    def test_explicit_contact_with_distinct_materials_analytic_network(self):
        raw = self.raw()
        raw["thermal"]["layers"][0]["sidewall_contacts"] = [
            {"dies": ["a", "b"], "resistance_m2k_w": 1e-4}
        ]
        case = parse_case(raw)
        power, _ = rasterize(case)
        temperature, _ = solve_package(case, power)
        coupling = 1 / (100 / 3 + 1000 / 3 + 1000)
        sink_a, sink_b = 1 / (1000 + 1 / 3), 1 / (1000 + 10 / 3)
        determinant = sink_a * sink_b + coupling * (sink_a + sink_b)
        expected = 25 + 0.001 * np.array([sink_b + coupling, coupling]) / determinant
        np.testing.assert_allclose(
            temperature[np.isfinite(temperature)], expected, rtol=0, atol=1e-10
        )

    def test_contact_cannot_bridge_gap(self):
        raw = self.raw(1e-5)
        raw["thermal"]["layers"][0]["sidewall_contacts"] = [
            {"dies": ["a", "b"], "resistance_m2k_w": 0}
        ]
        with self.assertRaisesRegex(ModelError, "cannot bridge"):
            parse_case(raw)

    def test_shared_package_still_conducts_between_die_projections(self):
        raw = self.raw()
        raw["thermal"]["layers"].insert(
            0,
            dict(
                id="base", footprint="package", thickness_mm=0.2, conductivity_w_mk=150
            ),
        )
        case = parse_case(raw)
        matrix, _, _, _, ids, _ = assemble_package(case, rasterize(case)[0])
        self.assertLess(matrix[ids[0, 0, 0], ids[0, 0, 1]], 0)
        self.assertEqual(matrix[ids[1, 0, 0], ids[1, 0, 1]], 0)

    def test_contact_y_normal_uses_y_conductivity(self):
        raw = self.raw()
        raw["package_mm"] = dict(width=1, height=3)
        raw["chiplets"][1]["placement_mm"] = dict(x=0, y=1)
        layer = raw["thermal"]["layers"][0]
        layer.pop("conductivity_w_mk")
        layer["conductivity_xyz_w_mk"] = [300, 150, 150]
        layer["die_materials"]["b"] = dict(conductivity_xyz_w_mk=[300, 15, 15])
        layer["sidewall_contacts"] = [dict(dies=["a", "b"], resistance_m2k_w=1e-4)]
        case = parse_case(raw)
        matrix, _, _, _, ids, _ = assemble_package(case, rasterize(case)[0])
        self.assertAlmostEqual(
            -matrix[ids[0, 0, 0], ids[0, 1, 0]], 1 / (100 / 3 + 1000 / 3 + 1000)
        )

    def test_invalid_material_and_contact_assignments(self):
        for field, value in [
            ("die_materials", {"unknown": {"conductivity_w_mk": 150}}),
            ("die_materials", {"a": {"conductivity_xyz_w_mk": [150, -1, 150]}}),
            ("sidewall_contacts", [{"dies": ["a", {}], "resistance_m2k_w": 0}]),
        ]:
            raw = self.raw()
            raw["thermal"]["layers"][0][field] = value
            with self.assertRaises(ModelError):
                parse_case(raw)

    def test_offset_rectangle_preserves_material_area(self):
        raw = self.raw(1)
        layer = {
            "id": "base",
            "footprint": "rectangle",
            "rect_mm": {"x": 0.25, "y": 0, "width": 2.5, "height": 1},
            "thickness_mm": 0.2,
            "conductivity_w_mk": 100,
        }
        raw["thermal"]["layers"].insert(0, layer)
        case = parse_case(raw)
        power, _ = rasterize(case)
        _, _, _, _, ids, _ = assemble_package(case, power)
        self.assertAlmostEqual(case.mesh.areas_mm2[ids[0] >= 0].sum(), 2.5)
        _, result = solve_package(case, power)
        self.assertLess(abs(result["energy_balance_error_w"]), 1e-10)


if __name__ == "__main__":
    unittest.main()
