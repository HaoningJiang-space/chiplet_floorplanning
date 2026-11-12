import importlib.util
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
AVAILABLE=importlib.util.find_spec('klayout') is not None
if AVAILABLE:
    import klayout.db as db
    from check_tap_ihp_local_access import check,LAYERS,circle_signature


@unittest.skipUnless(AVAILABLE,'optional local layout validation requires klayout')
class LocalAccessCheckerTest(unittest.TestCase):
    def fixture(self):
        # Analytical rectangular stand-in tests the checker, not the source PCell.
        layout=db.Layout();layout.dbu=.001;cell=layout.create_cell('TEST')
        rectangles={'opening':(-17500,-17500,17500,17500),'tm2':(-25000,-25000,25000,25000),
                    'tv2':(-450,-450,450,450),'tv1':(-210,-210,210,210),
                    'tm1':(-950,-950,37500,950),'m5':(-310,-310,310,37500)}
        for name,rect in rectangles.items():cell.shapes(layout.layer(*LAYERS[name])).insert(db.Box(*rect))
        return layout,cell

    def test_analytic_access_and_displaced_cut(self):
        layout,cell=self.fixture()
        self.assertEqual(check(layout,cell,1,1,{})['status'],'local_geometry_subset_passed')
        cuts=cell.shapes(layout.layer(*LAYERS['tv1']));cuts.clear();cuts.insert(db.Box(790,-210,1210,210))
        result=check(layout,cell,1,1,{})
        self.assertGreater(result['findings']['tv1_outside_m5'],0)

    def test_narrow_trace_and_missing_cut_rejected(self):
        for kind in ('narrow','missing'):
            layout,cell=self.fixture()
            layer='m5' if kind=='narrow' else 'tv2'
            shapes=cell.shapes(layout.layer(*LAYERS[layer]));shapes.clear()
            if kind=='narrow':shapes.insert(db.Box(-50,-310,50,37500))
            with self.subTest(kind=kind):
                self.assertEqual(check(layout,cell,1,1,{})['status'],'local_geometry_subset_failed')

    def test_exemption_is_not_blanket_layer_exemption(self):
        layout,cell=self.fixture()
        template=circle_signature(db.Polygon(db.Box(-25000,-25000,25000,25000)))
        cell.shapes(layout.layer(*LAYERS['tm2'])).insert(db.Box(50001,0,52001,2000))
        result=check(layout,cell,1,1,{'tm2':template})
        self.assertGreater(result['findings']['vertices_off_5nm_grid'],0)


if __name__=='__main__':unittest.main()
