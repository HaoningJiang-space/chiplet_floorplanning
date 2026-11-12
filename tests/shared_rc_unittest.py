"""Unique conductor capacitance and independent RC first-moment identities."""

import unittest

from chiplet_floorplanning.routing_graph import Fabric,Net,edge
from tools.validation.shared_routing_electrical import tree_rc,spef_tree
from tools.validation.shared_routing_fixture import shared_bottleneck


class SharedRCTests(unittest.TestCase):
    def test_two_edge_hand_first_moment(self):
        f=Fabric(3,1);n=Net('data','data',(0,0,0),((2,0,0),))
        edges={edge((0,0,0),(1,0,0)),edge((1,0,0),(2,0,0))}
        rc=tree_rc(f,n,edges)
        self.assertAlmostEqual(rc['total_parasitic_pf'],.008)
        self.assertAlmostEqual(rc['total_sink_pin_pf'],.01)
        self.assertAlmostEqual(rc['first_moment_ns'][0],5.6e-8,places=15)
        self.assertLess(rc['max_moment_difference_ns'],1e-15)

    def test_shared_prefix_capacitance_not_charged_per_sink(self):
        f,nets,routes=shared_bottleneck();n=nets[0]
        rc=tree_rc(f,n,routes[n.name])
        self.assertAlmostEqual(rc['total_parasitic_pf'],.1*.2)
        self.assertAlmostEqual(rc['total_sink_pin_pf'],.02)
        self.assertEqual(len(rc['conductors']),5)
        self.assertAlmostEqual(rc['first_moment_ns'][0],rc['first_moment_ns'][1],places=15)
        text=spef_tree('clock','driver:Y',['rx0:A','rx1:A'],rc)
        self.assertEqual(text.count('*D_NET '),1)
        self.assertEqual(text.count('*I driver:Y O'),1)
        self.assertEqual(text.count('*I rx0:A I'),1)

    def test_resistance_scaling_preserves_capacitance_and_scales_moment(self):
        f,nets,routes=shared_bottleneck();n=nets[0]
        a=tree_rc(f,n,routes[n.name]);b=tree_rc(f,n,routes[n.name],r_ohm_per_mm=10.)
        self.assertEqual(a['total_parasitic_pf'],b['total_parasitic_pf'])
        self.assertAlmostEqual(b['first_moment_ns'][0]/a['first_moment_ns'][0],100.)

    def test_via_has_distinct_declared_rc_and_invalid_coefficients_reject(self):
        f=Fabric(1,1,layers=2);n=Net('data','data',(0,0,0),((0,0,1),));edges={edge(*n.terminals)}
        rc=tree_rc(f,n,edges)
        self.assertAlmostEqual(rc['total_parasitic_pf'],.005)
        self.assertAlmostEqual(rc['first_moment_ns'][0],.01*(.0025+.01)*.001)
        with self.assertRaises(ValueError):
            tree_rc(f,n,edges,c_pf_per_mm=0.)


if __name__=='__main__':
    unittest.main()
