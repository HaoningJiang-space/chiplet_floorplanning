import unittest

import numpy as np

from chiplet_floorplanning.placement.common_move import HotspotResponse, common_landing, cooling_bounds
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet
from chiplet_floorplanning.placement.problem import Layout, Problem
from chiplet_floorplanning.placement.relocation import Landing


class CommonMoveTests(unittest.TestCase):
    def test_fractional_swap_bound_matches_observed_cell_after_a_full_solve(self):
        p = Problem("fractional", ("a","b"), np.array([[2500.,1700.],[1500.,3900.]]),
                    np.array([3.,7.]), (20000,20000), np.empty((0,2),int), np.empty((0,2,2)))
        xy = np.array([[7375.,5262.],[14112.,17890.]])
        start = Layout(xy, np.array([0,0]))
        bank = [Landing((),(),0.,0.), Landing((0,1),tuple(xy[::-1]),0.,0.)]
        sheet = CooledSheet(p, np.array([106.,107.]))
        row = HotspotResponse(sheet, sheet.power_map(start))
        bound = cooling_bounds(bank,start,p.size_um/1000,p.power_w,row)[1]
        final = sheet.temperatures(sheet.power_map(bank[1].apply(start)))
        self.assertAlmostEqual(bound, row.peak_k-final[row.cell_yx], places=9)
        self.assertGreaterEqual(bound+1e-9, row.peak_k-final.max())

    def test_new_hotspot_and_abstention(self):
        upper = [0, 4, 2, .5]
        real = [0, -1, 1.5, .4]
        chosen = common_landing(upper, [2,1,1,1], real.__getitem__)
        self.assertEqual((chosen.index,chosen.checked_moves), (2,2))
        self.assertEqual(common_landing([0,.08],[1,1],lambda _: .06).index,0)
