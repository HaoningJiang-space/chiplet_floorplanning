import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from tap_global_routing import bump_bins,build_graph,route,verify_witness,allowed_arcs
from audit_tap_capacity import source_capacities

class TapGlobalRoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[1]
        cls.entry=json.loads((root/'docs/evidence/tap-geometry-domains.json').read_text())['cases'][0]
        cls.domain=cls.entry['domain'];cls.placement=cls.entry['witness']['placement']
        cls.graph=build_graph(cls.domain,cls.placement)
        cls.demands=[[int(v) for v in row] for row in cls.domain['connection_wire_demands']]
        cls.result=route(cls.graph,cls.demands)

    def test_rotating_actual_bumps_preserves_source_pin_count(self):
        for p,c in zip(self.placement,self.domain['chiplets']):
            incident=sum(self.demands[p['id']])+sum(row[p['id']] for row in self.demands)
            _,caps=source_capacities(c['core_width_um']/1000,c['core_height_um']/1000,incident)
            for rotation in (p['rotation_deg'],(p['rotation_deg']+180)%360):
                self.assertEqual(sum(bump_bins(self.domain,dict(p,rotation_deg=rotation)).values()),sum(caps))

    def test_success_replays_without_solver(self):
        result=verify_witness(self.graph,self.demands,self.result['flows'])
        self.assertEqual(result['routed_wire_units'],2448)
        self.assertFalse(result['physical_qualified'])

    def test_missing_modified_duplicate_and_illegal_flows_rejected(self):
        f=self.result['flows']
        mutations=[f[:-1],f+[f[0]]]
        altered=copy.deepcopy(f);altered[0]['edges'][0][2]+=1;mutations.append(altered)
        altered=copy.deepcopy(f);altered[0]['edges'][0][0]=999999;mutations.append(altered)
        for flows in mutations:
            with self.assertRaises(ValueError):verify_witness(self.graph,self.demands,flows)

    def test_shared_capacity_recomputed_globally(self):
        graph=copy.deepcopy(self.graph)
        flow=self.result['flows'][0];u,v,amount=flow['edges'][0]
        graph['capacities'][min(u,v),max(u,v)]=amount-1
        with self.assertRaisesRegex(ValueError,'capacity'):verify_witness(graph,self.demands,self.result['flows'])

    def test_no_chip_transit_and_failure_not_infeasibility(self):
        arcs=allowed_arcs(self.graph,0,1)
        for i,node in self.graph['chips'].items():
            if i not in (0,1):self.assertFalse(any(node in e for e in arcs))
        graph=copy.deepcopy(self.graph)
        for edge in graph['capacities']:graph['capacities'][edge]=0
        self.assertEqual(route(graph,self.demands)['status'],'sequential_search_failed_unknown')

    def test_fractional_demand_and_zero_pitch_rejected(self):
        demands=copy.deepcopy(self.demands);demands[0][1]=.5
        with self.assertRaises(ValueError):verify_witness(self.graph,demands,self.result['flows'])
        with self.assertRaises(ValueError):build_graph(self.domain,self.placement,pitch_um=0)

if __name__=='__main__':unittest.main()
