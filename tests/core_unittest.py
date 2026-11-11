import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from chiplet_floorplanning.cli import evaluate
from chiplet_floorplanning.interconnect import estimate_links
from chiplet_floorplanning.model import Die, ModelError, Rect, load_case, parse_case
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.thermal import solve_steady


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "two_chiplets.json"


def raw_case():
    return json.loads(EXAMPLE.read_text())


class GeometryTests(unittest.TestCase):
    def test_all_rotations_and_bounding_boxes(self):
        # Hand-calculated transforms for a non-square die and asymmetric point.
        points = [(10.5, 20.25), (11.75, 20.5), (13.5, 21.75), (10.25, 23.5)]
        for rotation, expected in zip((0, 90, 180, 270), points):
            with self.subTest(rotation=rotation):
                die = Die("a", 4, 2, 10, 20, rotation, (), {})
                self.assertEqual(die.point(0.5, 0.25), expected)
                self.assertEqual(die.bounds.area, 8)
                self.assertEqual((die.bounds.width, die.bounds.height),
                                 (4, 2) if rotation in (0, 180) else (2, 4))
                self.assertEqual(die.transform(Rect(0.5, 0.25, 1, 0.5)).area, 0.5)

    def test_touching_dies_are_legal(self):
        data = raw_case()
        data["chiplets"][1]["placement_mm"]["x"] = 4
        parse_case(data)

    def test_invalid_inputs_rejected(self):
        mutations = [
            lambda d: d["chiplets"][1]["placement_mm"].update(x=2),
            lambda d: d["chiplets"][1]["placement_mm"].update(x=11),
            lambda d: d["chiplets"][0].update(rotation_deg=45),
            lambda d: d["chiplets"][0].update(rotation_deg=False),
            lambda d: d["chiplets"][0]["blocks"][0].update(power_w=-1),
            lambda d: d["chiplets"][0]["blocks"][0].update(power_w=float("nan")),
            lambda d: d["chiplets"][0]["blocks"][0].update(provenance=""),
            lambda d: d["chiplets"][0]["blocks"][1]["rect_mm"].update(x=1),
            lambda d: d["chiplets"][0]["blocks"][0]["rect_mm"].update(width=4),
            lambda d: d["chiplets"][0]["ports_mm"]["data"].update(x=4),
            lambda d: d["chiplets"][1].update(id="tx"),
            lambda d: d["links"][0]["target"].update(port="missing"),
            lambda d: d["links"][0]["target"].update(chiplet="tx"),
            lambda d: d["grid"].update(nx=0),
            lambda d: d["grid"].update(nx=True),
            lambda d: d["thermal"].update(sink_h_w_m2k=0),
            lambda d: d["thermal"].update(ambient_c=-300),
            lambda d: d["interconnect"].update(c_pf_per_mm=float("inf")),
            lambda d: d.update(typo=1),
            lambda d: d.update(schema_version=True),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                data = raw_case()
                mutation(data)
                with self.assertRaises(ModelError):
                    parse_case(data)

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"name": "one", "name": "two"}')
            with self.assertRaises(ModelError):
                load_case(path)

    def test_reference_link_geometry(self):
        links = estimate_links(load_case(EXAMPLE))
        for link in links:
            self.assertAlmostEqual(link["manhattan_length_mm"], 3)
            self.assertAlmostEqual(link["assumed_r_ohm"], 0.3)
            self.assertAlmostEqual(link["assumed_c_pf"], 0.6)
        self.assertEqual(links[0]["source_mm"], (4, 2.6))
        self.assertEqual(links[0]["target_mm"], (7, 2.6))


class PowerTests(unittest.TestCase):
    def test_non_aligned_sources_and_rotations_conserve_power(self):
        for rotation in (0, 90, 180, 270):
            for nx, ny in ((1, 1), (7, 11), (48, 32)):
                with self.subTest(rotation=rotation, grid=(nx, ny)):
                    data = raw_case()
                    data["grid"] = {"nx": nx, "ny": ny}
                    data["chiplets"][0]["rotation_deg"] = rotation
                    data["chiplets"][0]["placement_mm"] = {"x": 1.13, "y": 2.17}
                    power, records = rasterize(parse_case(data))
                    self.assertAlmostEqual(power.sum(), 3, places=12)
                    self.assertTrue(np.all(power >= 0))
                    for record in records:
                        self.assertAlmostEqual(record["input_w"], record["mapped_w"], places=12)

    def test_partial_coverage_known_weights(self):
        data = raw_case()
        data["package_mm"] = {"width": 4, "height": 2}
        data["grid"] = {"nx": 2, "ny": 1}
        data["links"] = []
        data["chiplets"] = [{"id": "a", "size_mm": {"width": 3, "height": 2},
                             "placement_mm": {"x": 0, "y": 0}, "rotation_deg": 0,
                             "ports_mm": {}, "blocks": [{"id": "b", "rect_mm": {
                                 "x": 1, "y": 0, "width": 2, "height": 2},
                                 "power_w": 6, "provenance": "analytic test"}]}]
        power, _ = rasterize(parse_case(data))
        np.testing.assert_allclose(power, [[3, 3]], rtol=0, atol=1e-14)

    def test_rotated_power_locations(self):
        data = raw_case()
        data["package_mm"] = {"width": 4, "height": 4}
        data["grid"] = {"nx": 4, "ny": 4}
        data["links"] = []
        data["chiplets"] = [{"id": "a", "size_mm": {"width": 2, "height": 1},
                             "placement_mm": {"x": 1, "y": 1}, "rotation_deg": 0,
                             "ports_mm": {}, "blocks": [{"id": "b", "rect_mm": {
                                 "x": 0, "y": 0, "width": 1, "height": 1},
                                 "power_w": 2, "provenance": "analytic test"}]}]
        for rotation, position in [(0, (1, 1)), (90, (1, 1)), (180, (1, 2)), (270, (2, 1))]:
            data["chiplets"][0]["rotation_deg"] = rotation
            power, _ = rasterize(parse_case(data))
            expected = np.zeros((4, 4))
            expected[position] = 2
            np.testing.assert_allclose(power, expected, rtol=0, atol=1e-14)


class ThermalTests(unittest.TestCase):
    def test_zero_power_equals_ambient(self):
        case = load_case(EXAMPLE)
        result, summary = solve_steady(case, np.zeros((case.ny, case.nx)))
        np.testing.assert_array_equal(result, np.full(result.shape, 25.0))
        self.assertEqual(summary["removed_heat_w"], 0)

    def test_uniform_heat_analytic_solution_multiple_meshes(self):
        # Insulated sides + constant q: T = T_ambient + P / (h * package_area).
        for nx, ny in ((1, 1), (1, 9), (8, 1), (7, 11), (48, 32)):
            data = raw_case()
            data["grid"] = {"nx": nx, "ny": ny}
            case = parse_case(data)
            result, summary = solve_steady(case, np.full((ny, nx), 3 / (nx * ny)))
            expected = 25 + 3 / (10000 * 12e-3 * 8e-3)
            np.testing.assert_allclose(result, expected, rtol=0, atol=1e-9)
            self.assertAlmostEqual(summary["removed_heat_w"], 3, places=9)

    def test_two_node_network_independent_solution(self):
        data = raw_case()
        data["grid"] = {"nx": 2, "ny": 1}
        case = parse_case(data)
        # Two 6 mm x 8 mm cells: sink = 0.48 W/K; coupling = 1/15 W/K.
        sink, coupling = 0.48, 1 / 15
        determinant = sink * (sink + 2 * coupling)
        expected = 25 + np.array([[(sink + coupling) / determinant, coupling / determinant]])
        result, _ = solve_steady(case, [[1, 0]])
        np.testing.assert_allclose(result, expected, rtol=0, atol=1e-12)

    def test_local_source_superposition_symmetry_and_heat_balance(self):
        case = load_case(EXAMPLE)
        power, _ = rasterize(case)
        result, summary = solve_steady(case, power)
        mirrored, _ = solve_steady(case, power[:, ::-1])
        doubled, _ = solve_steady(case, 2 * power)
        np.testing.assert_allclose(result[:, ::-1], mirrored, atol=1e-9, rtol=0)
        np.testing.assert_allclose(2 * (result - 25), doubled - 25, atol=1e-9, rtol=0)
        self.assertGreaterEqual(float(result.min()), 25)
        self.assertLess(abs(summary["energy_balance_error_w"]), 1e-9)

    def test_invalid_power_array(self):
        case = load_case(EXAMPLE)
        for power in [np.zeros((1, 1)), np.full((case.ny, case.nx), -1),
                      np.full((case.ny, case.nx), np.nan)]:
            with self.assertRaises(ValueError):
                solve_steady(case, power)


class ArtifactTests(unittest.TestCase):
    def test_report_snapshot_hash_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            report = evaluate(load_case(EXAMPLE), output)
            self.assertEqual(report["provenance"]["input_snapshot_sha256"],
                             hashlib.sha256((output / "input.json").read_bytes()).hexdigest())
            self.assertEqual(report["timing"]["status"], "not_run")
            self.assertIsNone(report["timing"]["setup_slack_ns"])
            self.assertEqual(report["thermal"]["calibration"], "not_calibrated")
            self.assertEqual(len((output / "grid.csv").read_text().splitlines()), 1537)
            with self.assertRaises(ValueError):
                evaluate(load_case(EXAMPLE), output)

    def test_cli_success_and_input_error(self):
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, "-m", "chiplet_floorplanning", "evaluate", str(EXAMPLE),
                                  "--output", str(Path(directory) / "run")], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            bad = Path(directory) / "bad.json"
            bad.write_text('{"name": "invalid"}')
            run = subprocess.run([sys.executable, "-m", "chiplet_floorplanning", "validate", str(bad)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertIn("missing fields", run.stderr)
            self.assertNotIn("Traceback", run.stderr)


if __name__ == "__main__":
    unittest.main()
