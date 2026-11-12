"""Hand-calculated shared-clock events and correlation controls."""

from dataclasses import replace
import unittest

from tools.validation.multilane_oracle import Network, expected


class MultiLaneTests(unittest.TestCase):
    def test_first_lane_hand_calculated_arrivals(self):
        c = Network()
        for check, edge, arrival, capture, required, slack in (
            ('setup','rise',2.3,6.4,6.2,3.9), ('setup','fall',2.7,6.4,6.05,3.35),
            ('hold','rise',2.3,-3.6,-3.45,5.75), ('hold','fall',2.7,-3.6,-3.5,6.2)):
            row = expected(c,0,0,check,edge)
            for key,value in zip(('data_arrival_ns','capture_arrival_ns','required_ns','slack_ns'),(arrival,capture,required,slack)):
                self.assertAlmostEqual(row[key],value)

    def test_shared_root_equal_delay_cancels_but_duty_distortion_does_not(self):
        c = Network()
        for check, sign in (('setup',1),('hold',-1)):
            base = expected(c,0,0,check,'rise')
            equal = expected(replace(c,root_ns=(.9,1.1)),0,0,check,'rise')
            duty = expected(replace(c,root_ns=(.4,1.1)),0,0,check,'rise')
            self.assertAlmostEqual(equal['data_arrival_ns']-base['data_arrival_ns'],.5)
            self.assertAlmostEqual(equal['slack_ns'],base['slack_ns'])
            self.assertAlmostEqual(duty['slack_ns']-base['slack_ns'],sign*.5)

    def test_correlated_common_root_is_one_parameter(self):
        c = Network()
        for check, edge, target in (('setup','rise',3.36),('setup','fall',2.81),('hold','rise',5.18),('hold','fall',5.51)):
            corrected = expected(c,0,0,check,edge,True,True)
            pessimistic = expected(c,0,0,check,edge,True,False)
            self.assertAlmostEqual(corrected['slack_ns'],target)
            self.assertAlmostEqual(corrected['slack_ns'],corrected['correlated_root_enumerated_slack_ns'])
            self.assertAlmostEqual(corrected['slack_ns']-pessimistic['slack_ns'],.2)

    def test_data_and_clock_branch_perturbations_have_distinct_scope(self):
        c = Network(receivers=3)
        for receiver in range(3):
            for lane in range(8):
                base = expected(c,receiver,lane,'setup','rise')['slack_ns']
                data = expected(replace(c,selected_data_shift_ns=.5),receiver,lane,'setup','rise')['slack_ns']
                branch = expected(replace(c,selected_branch_shift_ns=.5),receiver,lane,'setup','rise')['slack_ns']
                self.assertAlmostEqual(data-base,-.5 if (receiver,lane)==(0,0) else 0.)
                self.assertAlmostEqual(branch-base,.5 if receiver==0 else 0.)

    def test_long_clock_delay_does_not_repair_logical_hold_pair(self):
        row = expected(Network(trunk_ns=(7.8,8.)),0,0,'hold','rise')
        self.assertEqual(row['capture_edge_ns'],-6.)
        self.assertAlmostEqual(row['slack_ns'],-1.25)

    def test_invalid_fixture_domain_rejected(self):
        for change in (dict(receivers=0),dict(lanes=9),dict(lanes=True),dict(fall_ns=10),dict(root_ns=(0.,1.)),dict(selected_data_shift_ns=float('nan'))):
            with self.assertRaises(ValueError):
                Network(**change)


if __name__ == '__main__':
    unittest.main()
