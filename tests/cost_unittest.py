import math
import unittest

from chiplet_floorplanning.placement.cost import CostParams, defect_yield, dies_per_wafer, interposer_cost, option


class CostTest(unittest.TestCase):
    def test_yield_matches_the_hand_computed_reference(self):
        # Chiplet Actuary defaults: one full reticle (858 mm^2) yields about 0.61, 2,500 mm^2 about 0.26.
        self.assertAlmostEqual(defect_yield(858, 0.06, 6), 0.6102, places=3)
        self.assertAlmostEqual(defect_yield(2500, 0.06, 6), 0.2621, places=3)
        self.assertAlmostEqual(dies_per_wafer(100.0), math.pi*150**2/100 - math.pi*300/math.sqrt(200))

    def test_options_by_size(self):
        self.assertEqual(option(25, 32), ('single', 1))
        self.assertEqual(option(32, 25), ('single', 1))          # either orientation fits the field
        self.assertEqual(option(27, 27), ('stitched', 2))        # 729 mm^2, but 27 mm exceeds the 26 mm side
        self.assertEqual(option(42, 42), ('stitched', 4))        # 2 x 2 fields in either orientation
        self.assertEqual(option(50, 30), ('stitched', 2))        # 50 along the 33 mm side: 2 x 1
        self.assertEqual(option(59, 61), (None, 0))              # silicon only by default (no RDL thermal model)
        self.assertEqual(option(59, 61, CostParams(allow_rdl=True))[0], 'rdl_bridge')
        self.assertEqual(option(50, 152), (None, 0))

    def test_cost_grows_with_area_and_jumps_at_a_new_field(self):
        p = CostParams()
        costs = [interposer_cost(s, s, p)['total_usd'] for s in (30, 35, 40, 45, 50)]
        self.assertTrue(all(a < b for a, b in zip(costs, costs[1:])))
        below, above = interposer_cost(50, 32.99, p), interposer_cost(50, 33.01, p)    # height crosses one field
        self.assertEqual((below['fields'], above['fields']), (2, 4))
        for side, row in ((32.99, below), (33.01, above)):     # defect yield times one seam factor per extra field
            self.assertAlmostEqual(row['yield_'], defect_yield(50*side, p.d0_per_cm2, p.cluster)*p.seam_yield**(row['fields'] - 1))
        self.assertGreater(above['total_usd'], below['total_usd'])
        self.assertTrue(math.isinf(interposer_cost(50, 152, p)['total_usd']))

    def test_no_cheaper_option_appears_past_the_stitching_limit_by_default(self):
        # Review of b50044e: 2,831.399 -> 2,831.401 mm^2 switched stitched silicon to RDL and the cost halved.
        p = CostParams()
        side = (p.stitch_limit*858)**0.5
        self.assertTrue(math.isfinite(interposer_cost(side - 0.001, side - 0.001, p)['total_usd']))
        self.assertTrue(math.isinf(interposer_cost(side + 0.001, side + 0.001, p)['total_usd']))


if __name__ == '__main__':
    unittest.main()
