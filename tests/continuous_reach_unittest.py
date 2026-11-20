import unittest

import numpy as np

from chiplet_floorplanning.placement import heat_directed_moves, is_legal
from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.pin_reach import PinReachCell, reach_rows
from chiplet_floorplanning.placement.problem import Layout, Problem
from chiplet_floorplanning.placement.thermal import solve, thermal_case_data
from chiplet_floorplanning.placement.thermal_projection import projected_field


class ContinuousReachTest(unittest.TestCase):
    def setUp(self):
        self.p = Problem('two',('a','b'),np.array([[3000,5000],[4000,2000]]),np.array([5.,3.]),
                         (20000,20000),np.array([[0,1],[1,0],[0,0]]),
                         np.array([[[1000,500],[-1000,800]],[[1000,600],[-500,1800]],[[0,0],[900,0]]]))

    def test_grouped_rows_equal_worst_individual_pin_excess(self):
        limits = np.array([8.,14.,.8])
        for i in range(4):
            for j in range(4):
                lay=Layout(np.array([[4000.,10000.],[12000.,8000.]]),np.array([90*i,90*j]))
                rows,rhs=reach_rows(self.p,lay.rotation_deg,limits,4)
                violation=(rows@(lay.centre_um.T.ravel()/1000)-rhs).max()
                self.assertAlmostEqual(violation,(pin_manhattan_um(self.p,lay)/1000-limits).max())

    def test_energy_bound_survives_changed_geometry(self):
        for y in (6000.,12000.):
            lay=Layout(np.array([[5000.,5000.],[15000.,y]]),np.array([0,90]))
            approx,_,_=projected_field(self.p,lay,resolution=20,block_mm=12.)
            exact=solve(thermal_case_data(self.p,lay,100,20))[0]
            self.assertGreater(approx['lower_peak_c'],45.)
            self.assertLessEqual(approx['lower_peak_c'],exact['peak_power_layer_c'])
            self.assertLess(approx['reduced_nodes'],approx['full_nodes'])

    def test_tight_link_forces_follower_in_temperature_direction(self):
        p=Problem('two',('a','b'),np.full((2,2),2000.),np.array([5.,3.]),(14000,10000),
                  np.array([[0,1]]),np.zeros((1,2,2)))
        start=Layout(np.array([[4000.,5000.],[7000.,5000.]]),np.zeros(2,int))
        cell=PinReachCell(p,start,100,np.array([3.]),.003)
        delta,predicted=cell.cool_direction(start,np.array([80.]),np.array([[[1.,0.],[0.,0.]]]),1.)
        self.assertAlmostEqual(predicted,79.)
        np.testing.assert_allclose(delta,[[-1.,0.],[-1.,0.]],atol=2e-6)

    def test_public_entry_point_preserves_custom_signal_caps(self):
        start=Layout(np.array([[5000.,5000.],[10000.,6000.]]),np.array([0,90]))
        lengths=pin_manhattan_um(self.p,start)/1000
        limits=lengths+np.array([.1,1.,2.])
        start_m=lengths.sum()/1000
        model,moves=heat_directed_moves(self.p,start,limits,start_m,resolution=24)
        self.assertEqual(len(model['hot_dies']),2)
        self.assertGreaterEqual(len(moves),1)
        for _,pose,_ in moves:
            self.assertTrue(is_legal(self.p,pose,100))
            new=pin_manhattan_um(self.p,pose)/1000
            self.assertTrue(np.all(new<=limits+1e-9))
            self.assertLessEqual(new.sum()/1000,start_m+1e-9)
