import copy
import itertools
import json
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
from tools.validation.ranking import common_cohort, summarize


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


if __name__ == "__main__":
    unittest.main()
