"""Physical conductor ownership, cut proofs and exhaustive routing controls."""

from dataclasses import replace
import copy
import unittest

from chiplet_floorplanning.routing_graph import Fabric,Net,edge,audit,cut_certificate,verify_cut,route_greedy
from tools.validation.routing_exhaustive import enumerate_assignments
from tools.validation.shared_routing_fixture import shared_bottleneck,greedy_counterexample,scalable


class SharedRoutingTests(unittest.TestCase):
    def test_multicast_uses_one_cut_slot_and_one_copy_of_each_conductor(self):
        fabric,nets,routes=shared_bottleneck()
        result=audit(fabric,nets,routes)
        self.assertTrue(result['fabric_legal'])
        self.assertEqual(result['nets']['clock']['physical_edges'],5)
        self.assertAlmostEqual(result['nets']['clock']['unique_total_length_mm'],.1)
        self.assertAlmostEqual(result['nets']['clock']['sum_source_sink_path_length_mm'],.16)
        certificate=cut_certificate(fabric,nets,1)
        self.assertEqual((certificate['demand'],certificate['capacity']),(1,1))
        self.assertFalse(verify_cut(fabric,nets,certificate))

    def test_scale_and_paired_capacity_proof(self):
        for receivers in (1,3,7,15):
            fabric,nets=scalable(receivers)
            result=route_greedy(fabric,nets)
            self.assertEqual(result['status'],'feasible')
            self.assertEqual(len(result['routes']),8*receivers+1)
            self.assertFalse(verify_cut(fabric,nets,cut_certificate(fabric,nets,3)))
            blocked,nets=scalable(receivers,blocked_clock=True)
            certificate=cut_certificate(blocked,nets,3)
            self.assertEqual(certificate['demand'],8*receivers+1)
            self.assertEqual(certificate['capacity'],8*receivers)
            self.assertTrue(verify_cut(blocked,nets,certificate))

    def test_greedy_failure_is_not_infeasibility(self):
        fabric,nets=greedy_counterexample()
        greedy=route_greedy(fabric,nets)
        self.assertEqual(greedy['status'],'search_failed')
        self.assertFalse(greedy['proven_infeasible'])
        exact=enumerate_assignments(fabric,nets)
        self.assertEqual(exact['status'],'feasible')
        self.assertTrue(audit(fabric,nets,exact['routes'])['fabric_legal'])
        self.assertEqual(exact['complete_simple_path_counts'],{'a':[2],'b':[7]})

    def test_crossing_case_is_exhaustively_infeasible(self):
        fabric=Fabric(3,3)
        nets=(Net('a','data',(0,1,0),((2,1,0),)),Net('b','data',(1,0,0),((1,2,0),)))
        exact=enumerate_assignments(fabric,nets)
        self.assertEqual(exact['status'],'exhaustive_infeasible')
        self.assertTrue(exact['proven_infeasible'])
        limited=enumerate_assignments(fabric,nets,max_states=1)
        self.assertEqual(limited['status'],'exhaustive_limit')
        self.assertFalse(limited['proven_infeasible'])

    def test_certificate_cannot_omit_tracks_or_duplicate_clock_demand(self):
        fabric,nets,_=shared_bottleneck()
        original=cut_certificate(fabric,nets,1)
        altered=copy.deepcopy(original);altered['demand']=2;altered['proven_infeasible']=True
        with self.assertRaises(ValueError):
            verify_cut(fabric,nets,altered)
        with self.assertRaises(ValueError):
            verify_cut(Fabric(4,3),nets,original)

    def test_invalid_conductor_trees_rejected(self):
        fabric,nets,routes=shared_bottleneck()
        missing={'clock':routes['clock']-{edge((3,1,0),(3,2,0))}}
        self.assertFalse(audit(fabric,nets,missing)['fabric_legal'])
        dangling={'clock':routes['clock']|{edge((0,1,0),(0,0,0))}}
        self.assertFalse(audit(fabric,nets,dangling)['fabric_legal'])
        cycle={'clock':routes['clock']|{edge((0,1,0),(0,0,0)),edge((0,0,0),(1,0,0)),edge((1,0,0),(1,1,0))}}
        self.assertFalse(audit(fabric,nets,cycle)['fabric_legal'])
        blocked=replace(fabric,blocked_edges=fabric.blocked_edges|{edge((2,1,0),(3,1,0))})
        self.assertFalse(audit(blocked,nets,routes)['fabric_legal'])

    def test_different_nets_cannot_share_nodes_even_without_sharing_edges(self):
        fabric=Fabric(3,3)
        nets=(Net('a','data',(0,1,0),((2,1,0),)),Net('b','data',(1,0,0),((1,2,0),)))
        routes={'a':{edge((0,1,0),(1,1,0)),edge((1,1,0),(2,1,0))},
                'b':{edge((1,0,0),(1,1,0)),edge((1,1,0),(1,2,0))}}
        self.assertFalse(audit(fabric,nets,routes)['fabric_legal'])

    def test_dimension_and_terminal_ownership_guards(self):
        for values in (dict(pitch_um=19.),dict(via_landing_um=11.),dict(layers=True),dict(layer_separation_um=0.)):
            with self.assertRaises(ValueError):
                Fabric(3,3,**values)
        nets=(Net('a','clock',(0,0,0),((2,0,0),)),Net('b','clock',(0,0,0),((2,2,0),)))
        with self.assertRaises(ValueError):
            route_greedy(Fabric(3,3),nets)


if __name__=='__main__':
    unittest.main()
