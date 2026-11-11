import copy
from pathlib import Path
import unittest

import numpy as np

from chiplet_floorplanning.model import load_case, parse_case, ModelError
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.package import solve_package
from chiplet_floorplanning.interconnect import estimate_links
from chiplet_floorplanning.timing import spef_network, run_timing

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/layered_two_chiplets.json"


class PackageTests(unittest.TestCase):
    def case(self):
        return load_case(EXAMPLE)

    def test_analytic_series_column_including_surface_half_cell(self):
        raw = copy.deepcopy(self.case().input_data)
        raw["grid"] = {"nx": 12, "ny": 8}
        for layer in raw["thermal"]["layers"]:
            layer["footprint"] = "package"
        raw["thermal"]["power_layer"] = "interposer"
        case = parse_case(raw)
        power = np.full((8, 12), 3 / 96)
        temperature, result = solve_package(case, power)
        area = 12e-3 * 8e-3
        layers = case.thermal["layers"]
        # The source is at the first layer centre; top heat flows through half
        # of that layer, all subsequent layers, then the surface convection.
        resistance = layers[0]["thickness_mm"]*1e-3 / (2*layers[0]["conductivity_w_mk"]*area)
        resistance += sum(layer["thickness_mm"]*1e-3/(layer["conductivity_w_mk"]*area) for layer in layers[1:])
        resistance += 1 / (case.thermal["top_h_w_m2k"] * area)
        np.testing.assert_allclose(temperature, 25+3*resistance, atol=1e-8, rtol=0)
        self.assertLess(abs(result["energy_balance_error_w"]), 1e-8)

    def test_zero_power_superposition_and_cooling(self):
        case = self.case()
        p, _ = rasterize(case)
        zero, _ = solve_package(case, np.zeros_like(p))
        np.testing.assert_allclose(zero[np.isfinite(zero)], 25, rtol=0, atol=0)
        temperature, _ = solve_package(case, p)
        doubled, _ = solve_package(case, 2*p)
        mask = np.isfinite(temperature)
        np.testing.assert_allclose(doubled[mask]-25, 2*(temperature[mask]-25), atol=1e-8, rtol=0)
        raw = copy.deepcopy(case.input_data)
        raw["thermal"]["top_h_w_m2k"] *= 2
        cooler, _ = solve_package(parse_case(raw), p)
        self.assertLess(np.nanmax(cooler), np.nanmax(temperature))

    def test_void_and_alignment(self):
        case = self.case()
        p, _ = rasterize(case)
        temperature, _ = solve_package(case, p)
        self.assertTrue(np.isnan(temperature[0, 0]))
        p[0, 0] = 1
        with self.assertRaises(ValueError):
            solve_package(case, p)
        raw = copy.deepcopy(case.input_data)
        raw["chiplets"][0]["placement_mm"]["x"] += 0.1
        bad = parse_case(raw)
        p, _ = rasterize(bad)
        with self.assertRaisesRegex(ValueError, "aligned"):
            solve_package(bad, p)

    def test_invalid_package(self):
        for field, value in [("top_h_w_m2k", 0), ("power_layer", "missing")]:
            raw = copy.deepcopy(self.case().input_data)
            raw["thermal"][field] = value
            with self.assertRaises(ModelError):
                parse_case(raw)

    def test_geometry_based_rc(self):
        links = estimate_links(self.case())
        self.assertAlmostEqual(links[0]["assumed_r_ohm"], 5.04)
        self.assertAlmostEqual(links[0]["assumed_c_pf"], 1.0359399740976)

    def test_spef_conserves_total_r_c(self):
        text = spef_network("data", "a:Q", "b:D", 10, 0.8, 8)
        caps = text.split("*CAP\n")[1].split("*RES\n")[0].splitlines()
        resistors = text.split("*RES\n")[1].split("*END")[0].splitlines()
        self.assertAlmostEqual(sum(float(row.split()[-1]) for row in caps), 0.8)
        self.assertAlmostEqual(sum(float(row.split()[-1]) for row in resistors), 10)
        for r, c in [(0, 1), (1, 0), (-1, 1)]:
            with self.assertRaises(ValueError):
                spef_network("data", "a:Q", "b:D", r, c)

    def test_missing_models_fail_before_output(self):
        with self.assertRaises(FileNotFoundError):
            run_timing(self.case(), "/nonexistent-chiplet-output", "/nonexistent-sta", "/nonexistent-lib1", "/nonexistent-lib2")


if __name__ == "__main__":
    unittest.main()
