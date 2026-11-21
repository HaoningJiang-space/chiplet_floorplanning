import unittest

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement.pin_reach import PinReachCell, required_travel_mm
from chiplet_floorplanning.placement.successors import follower_landing, proxy_peaks


class FollowerLandingTest(unittest.TestCase):
    def test_total_length_needs_help_without_a_tight_individual_link(self):
        p = Problem('chain', ('left','middle','right'), np.full((3,2), 2000.), np.ones(3),
                    (16000,10000), np.array([[0,1],[1,2]]), np.zeros((2,2,2)))
        start = Layout(np.array([[4000.,4000.],[8000.,4000.],[12000.,4000.]]), np.zeros(3,int))
        step = np.array([-1.,0.])
        reach = np.full(2,15.)
        _, lower = required_travel_mm(p,start,reach,np.tile(step,(3,1)))
        self.assertFalse(np.any(lower[0,1:] > 0))
        region = PinReachCell(p,start,100,reach,.008)
        self.assertIsNone(follower_landing(region,start,0,step,set(),1.))
        repaired = follower_landing(region,start,0,step,{1,2},1.)
        self.assertIsNotNone(repaired)
        np.testing.assert_allclose(repaired.centre_um[0], [3000.,4000.])
        self.assertLessEqual(repaired.centre_um[2,0],11000.)

    def test_locked_neighbour_prevents_move_and_released_neighbour_follows(self):
        p = Problem('pair', ('a','b'), np.full((2,2), 2000.), np.array([4., 8.]),
                    (16000,10000), np.array([[0,1]]), np.zeros((1,2,2)))
        for x, reach, step, pin_forced in [(8000, 4., -1., True), (6100, 9., 1., False)]:
            start = Layout(np.array([[4000.,4000.],[x,4000.]]), np.zeros(2,int))
            movement = np.array([step,0.])
            pin, cell = required_travel_mm(p,start,[reach],np.tile(movement,(2,1)))
            self.assertEqual(bool(pin[0,1]>0), pin_forced)
            self.assertGreater(cell[0,1],0)
            region = PinReachCell(p,start,100,np.array([reach]),.015)
            self.assertIsNone(follower_landing(region,start,0,movement,set(),1.))
            target = follower_landing(region,start,0,movement,{1},1.)
            np.testing.assert_allclose(target.centre_um-start.centre_um, np.tile(1000*movement,(2,1)))
            peaks = np.array([50.,55.])
            np.testing.assert_allclose(proxy_peaks(p,start,target,peaks,[1,0]),peaks[::-1])
