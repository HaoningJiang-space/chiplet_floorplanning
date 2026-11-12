import copy
import itertools
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

import numpy as np

from chiplet_floorplanning.layout import (
    corridor_routes,
    evaluate_layout,
    relocate_design,
)
from chiplet_floorplanning.model import load_case
from chiplet_floorplanning.routing import (
    PlanarRules,
    audit_routes,
    route_length_mm,
    shortest_path,
    shortest_route_pairs,
    with_routes,
)
from tools.validation.ranking import common_cohort, compare_reference, summarize


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.base = load_case("examples/low_speed_gpio.json")
        with open("examples/planar_routing_contract.json") as stream:
            self.contract = json.load(stream)
        self.rules = PlanarRules.from_dict(self.contract)

    def test_obstacle_detour_matches_independent_analytic_length(self):
        route = shortest_path((1, 4), (9, 4), 10, 8, 0.1, [(4, 3, 6, 5)])
        self.assertAlmostEqual(route_length_mm(route), 10)
        self.assertIsNone(shortest_path((1, 4), (9, 4), 10, 8, 0.1, [(4, -1, 6, 9)]))

    def test_all_27_shortest_pairs_attain_manhattan_bound_without_shorts(self):
        original = copy.deepcopy(self.base.input_data)
        for tx, rx, y in itertools.product((0.5, 1.5, 2.5), (6, 7, 8), (1, 2, 3)):
            case = relocate_design(
                self.base, dict(tx=dict(x=tx, y=y), rx=dict(x=rx, y=2))
            )
            self.assertTrue(all("route_points_mm" not in l for l in case.links))
            candidates = shortest_route_pairs(case, self.rules)
            self.assertTrue(candidates)
            self.assertAlmostEqual(
                candidates[0]["length_mm"], 2 * (rx - tx - 3 + abs(y - 2))
            )
            self.assertTrue(
                audit_routes(with_routes(case, candidates[0]["routes"]), self.rules)[
                    "geometry_legal"
                ]
            )
        self.assertEqual(self.base.input_data, original)

    def test_corridor_exchange_requires_crossovers_on_one_layer(self):
        for y in (1, 2, 3):
            case = relocate_design(self.base, {"tx": dict(x=1, y=y)})
            for data, clock, legal in ((1.5, 4.5, True), (4.5, 1.5, False)):
                routed = with_routes(
                    case, corridor_routes(case, dict(lane_data=data, lane_clock=clock))
                )
                self.assertEqual(
                    audit_routes(routed, self.rules)["geometry_legal"], legal
                )

    def test_wire_width_spacing_and_backtracking_are_not_point_checks(self):
        for gap, legal in ((0.015, False), (0.020, True)):
            routes = {
                "lane_data": [[4, 2.6], [7, 2.6]],
                "lane_clock": [[4, 3.4], [4, 2.6 + gap], [7, 2.6 + gap], [7, 3.4]],
            }
            self.assertEqual(
                audit_routes(with_routes(self.base, routes), self.rules)[
                    "geometry_legal"
                ],
                legal,
            )
        for data in (
            [[4, 2.6], [4, 0.001], [7, 0.001], [7, 2.6]],
            [[4, 2.6], [5, 2.6], [4.5, 2.6], [7, 2.6]],
        ):
            routes = {"lane_data": data, "lane_clock": [[4, 3.4], [7, 3.4]]}
            self.assertFalse(
                audit_routes(with_routes(self.base, routes), self.rules)[
                    "geometry_legal"
                ]
            )

    def test_explicit_keepout_is_avoided_and_unrouted_case_is_not_legal(self):
        rules = PlanarRules.from_dict(
            {**self.contract, "keepouts_mm": [dict(x=5, y=2.5, width=0.2, height=0.2)]}
        )
        self.assertFalse(audit_routes(self.base, rules)["geometry_legal"])
        candidates = shortest_route_pairs(self.base, rules)
        self.assertTrue(candidates)
        self.assertGreater(candidates[0]["length_mm"], 6)
        self.assertTrue(
            audit_routes(with_routes(self.base, candidates[0]["routes"]), rules)[
                "geometry_legal"
            ]
        )
        self.assertFalse(
            audit_routes(relocate_design(self.base, {}), self.rules)["geometry_legal"]
        )

    def test_profiling_preserves_thermal_results(self):
        timings = {}
        case = relocate_design(
            self.base,
            {},
            grid=dict(nx=12, ny=8, mode="geometry_conformal"),
            timings_s=timings,
        )
        a, b = evaluate_layout(case), evaluate_layout(case, timings_s=timings)
        np.testing.assert_allclose(
            a["temperature_c"], b["temperature_c"], rtol=0, atol=0, equal_nan=True
        )
        self.assertTrue(
            {
                "mesh_generation_s",
                "input_validation_s",
                "power_mapping_s",
                "matrix_assembly_s",
                "thermal_linear_solve_s",
            }
            <= timings.keys()
        )
        self.assertTrue(all(np.isfinite(v) and v >= 0 for v in timings.values()))


class NecessityTests(unittest.TestCase):
    def row(self, name, temp, slack):
        return dict(
            id=name,
            peak_c=temp,
            setup_slack_ns=slack,
            hold_slack_ns=100,
            worst_slack_ns=slack,
            timing_status="analyzed",
            mesh_peak_change_k=0.01,
            placement_mm=dict(tx=dict(y=1)),
        )

    def test_surplus_slack_does_not_displace_thermal_optimum(self):
        result = summarize([self.row("cold", 40, 1), self.row("hot", 45, 10)])
        self.assertEqual(result["conflict_count"], 1)
        self.assertEqual(result["constrained_thermal_optimum"], "cold")
        self.assertEqual(result["timing_constraint_thermal_penalty_k"], 0)

    def test_timing_filter_is_applied_after_thermal_baseline_selection(self):
        result = summarize([self.row("cold", 40, -0.1), self.row("hot", 45, 0.1)])
        self.assertEqual(result["thermal_optimum_before_timing_filter"], "cold")
        self.assertFalse(result["thermal_optimum_is_timing_feasible"])
        self.assertEqual(result["constrained_thermal_optimum"], "hot")
        self.assertEqual(result["timing_constraint_thermal_penalty_k"], 5)

    def test_electrical_and_setup_hold_costs_have_distinct_baselines(self):
        rejected = dict(self.row("electrical_fail", 35, 1), timing_status="electrically_rejected")
        result = summarize([rejected, self.row("timing_fail", 40, -1), self.row("accepted", 45, 1)])
        stages = result["constraint_stages"]
        self.assertEqual(stages["electrical_admission_penalty_k"], 5)
        self.assertEqual(stages["setup_hold_incremental_penalty_k"], 5)
        self.assertEqual(stages["combined_admission_penalty_k"], 10)
        self.assertEqual(result["timing_constraint_thermal_penalty_k"], 5)

    def test_empty_or_unsearched_sets_are_not_zero_cost_or_global_proofs(self):
        fails_hold = dict(self.row("fails_hold", 40, 1), hold_slack_ns=-1, worst_slack_ns=-1)
        empty = summarize([fails_hold])["constraint_stages"]
        self.assertIsNone(empty["setup_hold_incremental_penalty_k"])
        self.assertEqual(empty["feasible_set_status"], "empty_evaluated_subset")
        unknown = dict(self.row("unsearched", 30, 1), timing_status="routing_search_failed")
        result = summarize([unknown])["constraint_stages"]
        self.assertIsNone(result["combined_admission_penalty_k"])
        self.assertEqual(result["feasible_set_status"], "unresolved_candidates_remain")
        self.assertFalse(result["complete_design_space_infeasibility_proven"])

    def test_invalid_status_or_nonfinite_candidate_cannot_hide_in_minimum(self):
        for update in (dict(routing=dict(geometry_legal=False)), dict(peak_c=float("nan")),
                       dict(hold_slack_ns=float("inf"))):
            with self.subTest(update=update), self.assertRaises(ValueError):
                summarize([{**self.row("invalid", 40, 1), **update}])

    def test_missing_routing_cohort_is_not_zero_conflict_evidence(self):
        policies = {
            "R1": [self.row("a", 40, 1), self.row("b", 45, 2)],
            "R2": [self.row("a", 40, 2)],
            "R3": [],
        }
        result = common_cohort(policies)
        self.assertEqual(result["layout_ids"], ["a"])
        self.assertEqual(result["excluded_empty_policies"], ["R3"])
        self.assertIsNone(summarize([])["conflict_count"])
        self.assertIsNone(summarize([])["thermal_optimum_is_timing_feasible"])


class ReferenceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        raw = {"input": "fixed"}
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        self.row = dict(
            id="a",
            timing_status="analyzed",
            setup_slack_ns=8.0,
            hold_slack_ns=11.0,
            case_input_sha256=digest,
        )
        self.identity = dict(
            sta_sha256="build-a",
            libraries=["same-library"],
            period_ns=20,
            interface="same-interface",
        )
        (root / "a/sta").mkdir(parents=True)
        (root / "a/case.json").write_text(json.dumps(raw))
        self.timing = root / "a/sta/timing.json"
        self.timing.write_text(
            json.dumps(
                dict(
                    self.identity,
                    input_sha256=digest,
                    setup_slack_ns=8.0,
                    hold_slack_ns=11.0,
                )
            )
        )
        self.path = root / "report.json"
        self.path.write_text(json.dumps(dict(passed=True, candidates=[self.row])))

    def test_exact_reference_accepts_and_real_slack_change_fails(self):
        self.assertTrue(
            compare_reference([self.row], self.path, self.identity)["passed"]
        )
        changed = dict(self.row, setup_slack_ns=8.000001)
        self.assertFalse(
            compare_reference([changed], self.path, self.identity)["passed"]
        )

    def test_same_slack_does_not_hide_changed_inputs_build_or_clock_contract(self):
        for key, value in (
            ("sta_sha256", "other-build"),
            ("libraries", ["other-lib"]),
            ("period_ns", 10),
            ("interface", "other-interface"),
        ):
            with self.subTest(key=key):
                changed = {**self.identity, key: value}
                self.assertFalse(
                    compare_reference([self.row], self.path, changed)["passed"]
                )
        changed = dict(self.row, case_input_sha256="changed-input")
        self.assertFalse(
            compare_reference([changed], self.path, self.identity)["passed"]
        )
        inconsistent = json.loads(self.timing.read_text())
        inconsistent["hold_slack_ns"] = 11.000001
        self.timing.write_text(json.dumps(inconsistent))
        self.assertFalse(
            compare_reference([self.row], self.path, self.identity)["passed"]
        )


if __name__ == "__main__":
    unittest.main()
