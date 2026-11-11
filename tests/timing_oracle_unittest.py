"""Hand-derived event examples, independent of generated STA report parsing."""

from dataclasses import replace
import copy
import unittest

from tools.validation.timing_oracle import Contract, early_corner, expected_paths
from tools.validation.timing_report import compare_builds


class TimingEventTests(unittest.TestCase):
    def test_hand_calculated_nominal_events(self):
        paths = expected_paths(Contract())
        for name, reference in {
            "setup_rise": (4, 2, 5.5, 5.3, 3.3),
            "setup_fall": (4, 2.1, 5.5, 5.15, 3.05),
            "hold_rise": (-6, 2, -4.5, -4.35, 6.35),
            "hold_fall": (-6, 2.1, -4.5, -4.4, 6.5),
        }.items():
            for field, value in zip(("capture_edge_ns", "data_arrival_ns",
                                     "capture_arrival_ns", "required_ns", "slack_ns"), reference):
                self.assertAlmostEqual(paths[name][field], value)

    def test_early_late_hand_calculation(self):
        c = Contract()
        paths = expected_paths(c, early_corner(c))
        for name, value in {"setup_rise": 2.6, "setup_fall": 2.35,
                            "hold_rise": 5.45, "hold_fall": 5.6}.items():
            self.assertAlmostEqual(paths[name]["slack_ns"], value)

    def test_late_clock_cannot_repair_hold_by_repairing_edge(self):
        paths = expected_paths(replace(Contract(), clock_ns=(7.9, 8.1)))
        self.assertAlmostEqual(paths["hold_rise"]["capture_edge_ns"], -6)
        self.assertAlmostEqual(paths["hold_rise"]["slack_ns"], -0.65)

    def test_period_and_duty_cycle_have_different_effects(self):
        period = expected_paths(replace(Contract(), period_ns=12))
        duty = expected_paths(replace(Contract(), fall_ns=6))
        self.assertAlmostEqual(period["setup_rise"]["slack_ns"], 3.3)
        self.assertAlmostEqual(period["hold_rise"]["slack_ns"], 8.35)
        self.assertAlmostEqual(duty["setup_rise"]["slack_ns"], 5.3)
        self.assertAlmostEqual(duty["hold_rise"]["slack_ns"], 4.35)

    def test_common_delay_changes_arrivals_not_slack(self):
        paths = expected_paths(replace(Contract(), data_ns=(1.8, 1.7), clock_ns=(1.4, 1.6)))
        self.assertAlmostEqual(paths["setup_rise"]["capture_arrival_ns"], 6)
        self.assertAlmostEqual(paths["setup_rise"]["data_arrival_ns"], 2.5)
        self.assertAlmostEqual(paths["setup_rise"]["slack_ns"], 3.3)
        self.assertAlmostEqual(paths["hold_rise"]["slack_ns"], 6.35)

    def test_invalid_clock_phase_is_rejected(self):
        for phase in (0, 10, 11):
            with self.assertRaises(ValueError):
                expected_paths(replace(Contract(), fall_ns=phase))

    def test_cross_build_compares_arrivals_not_only_slack(self):
        reference = {"nominal": {"input_sha256": {"fixture.lib": "same"},
                                 "observed": {"slack_ns": 3.3, "data_arrival_ns": 2,
                                              "cap_pf": 0.01}}}
        altered = copy.deepcopy(reference)
        altered["nominal"]["observed"]["data_arrival_ns"] += 0.2
        with self.assertRaisesRegex(ValueError, "data_arrival_ns"):
            compare_builds(altered, reference, 1e-5)

    def test_cross_build_rejects_different_inputs(self):
        a = {"nominal": {"input_sha256": {"fixture.lib": "a"}}}
        b = {"nominal": {"input_sha256": {"fixture.lib": "b"}}}
        with self.assertRaisesRegex(ValueError, "inputs differ"):
            compare_builds(a, b, 1e-5)


if __name__ == "__main__":
    unittest.main()
