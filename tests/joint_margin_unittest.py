import unittest

import numpy as np

from chiplet_floorplanning.placement.common_move import HotspotResponse
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet
from chiplet_floorplanning.placement.footprint_response import FootprintResponse
from chiplet_floorplanning.placement.joint_assignment import JointAssignment
from chiplet_floorplanning.placement.joint_generation import JointLandings
from chiplet_floorplanning.placement.joint_margin import PairMargin
from chiplet_floorplanning.placement.problem import Layout, Problem


class JointMarginTest(unittest.TestCase):
    def test_fractional_matrix_reuses_the_signed_footprint_integrals(self):
        p = Problem("fractional",("a","b"),np.array([[1800.,1700.],[2100.,1300.]]),
                    np.array([1.3,3.2]),(9000.,8500.),np.array([[0,1]]),np.zeros((1,2,2)))
        start = Layout(np.array([[1500.,2225.],[6000.,4550.]]),np.array([90,0]))
        d = JointLandings(p,p,start,None,1.)
        sheet = CooledSheet(p,np.array([88.,100.]))
        initial = sheet.temperatures(sheet.power_map(start))
        for cell in ((50,49),(60,58)):
            row = HotspotResponse.at_cell(sheet,initial,cell)
            projected = FootprintResponse(d,row).cooling(row)
            d.observe(row)
            np.testing.assert_allclose(projected,d.cooling[-1],atol=1e-10,rtol=0)

    def test_block_selection_and_integer_assignment_agree_with_every_feasible_pair(self):
        p = Problem("wire", ("a","b","c"), np.full((3,2),800.), np.array([2.,4.,3.]), (5000.,4000.),
                    np.array([[0,1],[2,0],[1,0]]), np.array([[[50.,20.],[5.,75.]],[[0.,5.],[10.,0.]],[[0.,15.],[0.,50.]]]))
        start = Layout(np.array([[1000.,1000.],[3000.,1000.],[2000.,3000.]]), np.zeros(3,int))
        d = JointLandings(p,p,start,None, .008)
        rng = np.random.default_rng(1331)
        d.cooling = list(rng.normal(size=(5,len(d.xy))))
        d.headroom = [0.,.2,.1,.4,.5]
        exhaustive = []
        for i in range(len(d.xy)):
            js, costs = d.partners(i)
            for j, cost in zip(js,costs):
                if i<j:
                    score = min(h+c[i]+c[j] for h,c in zip(d.headroom,d.cooling))
                    exhaustive.append((-score,cost,(i,int(j))))
        pair = PairMargin(d,block_size=3)
        many = JointAssignment(d,2,2)
        excluded = set()
        for minus,cost,key in sorted(exhaustive)[:3]:
            for model in (pair,many):
                found,move,score = model.propose(excluded)
                self.assertEqual(found,key)
                self.assertAlmostEqual(move.cost,cost)
                self.assertAlmostEqual(score,-minus)
            excluded.add(key)
