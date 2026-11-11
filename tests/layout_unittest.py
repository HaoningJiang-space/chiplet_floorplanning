import copy
import unittest
from chiplet_floorplanning.model import load_case, ModelError
from chiplet_floorplanning.layout import place_design
from chiplet_floorplanning.interconnect import estimate_links


class LayoutTests(unittest.TestCase):
    def test_design_invariants_and_independent_routes(self):
        base = load_case("examples/low_speed_gpio.json")
        before = copy.deepcopy(base.input_data)
        placed = place_design(
            base,
            {"tx": dict(x=0.5, y=1)},
            corridors_y_mm=dict(lane_data=1.5, lane_clock=4.5),
        )
        other = place_design(
            base,
            {"tx": dict(x=0.5, y=1)},
            corridors_y_mm=dict(lane_data=0.5, lane_clock=4.5),
        )
        a, b = estimate_links(placed), estimate_links(other)
        self.assertEqual(a[1], b[1])
        self.assertAlmostEqual(b[0]["modeled_length_mm"] - a[0]["modeled_length_mm"], 2)
        self.assertEqual(base.input_data, before)
        self.assertEqual(placed.input_data["thermal"], before["thermal"])
        self.assertEqual(sum(b.power_w for d in placed.dies for b in d.blocks), 3)

    def test_overlap_and_missing_routes_rejected(self):
        base = load_case("examples/low_speed_gpio.json")
        with self.assertRaises(ModelError):
            place_design(
                base,
                {"tx": dict(x=7, y=2)},
                corridors_y_mm=dict(lane_data=1.5, lane_clock=4.5),
            )
        with self.assertRaises(ModelError):
            place_design(base, {}, corridors_y_mm=dict(lane_data=1.5))
