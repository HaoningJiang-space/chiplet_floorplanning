from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.integrate import solve_bvp

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from validation.ttc_spectral import impedance,transfer


class TTCSpectralTest(unittest.TestCase):
    def test_uniform_planar_sources_have_only_zero_mode(self):
        properties={'SILICON':{'conductivity_w_per_m_k':88.},'SILICONE':{'conductivity_w_per_m_k':14.3}}
        geometry=dict(die_side_um=10000.,active_silicon_um=15.,bulk_silicon_um=610.,thermal_pad_um=500.,
                      materials={'natural':properties},sensors_xy_um=[[1000+i*500,3000] for i in range(16)],
                      heaters=[dict(x_um=0,y_um=0,width_um=10000,height_um=10000,power_index=i,power_fraction=1.) for i in range(16)])
        r=transfer(geometry,'heatsink',.2,32)
        expected=1/.2+impedance(np.array([0.]),.000015,.000610,.0005,88.,14.3)[0]/.01**2
        np.testing.assert_allclose(r,np.full((16,16),expected),atol=1e-12)

    def test_zero_mode_quadratic_limit(self):
        expected=3*.000015/(8*88)+.000610/88+.0005/14.3
        z=impedance(np.array([0.,.5]),.000015,.000610,.0005,88.,14.3)
        self.assertAlmostEqual(z[0],expected,places=14)
        self.assertLess(abs(z[1]-z[0])/z[0],1e-6)

    def test_independent_boundary_value_ode_with_discontinuous_material(self):
        # Use three separately parameterized segments so BVP mesh endpoints
        # represent exact interfaces. Unknowns: T and upward heat flux per
        # segment; enforce flux and temperature continuity at interfaces.
        a,b,p=.000015,.000610,.0005
        thickness=np.array([a,b,p]);k=np.array([88.,88.,14.3])
        for q in (0.,300.,3000.,30000.,300000.):
            def ode(s,y):
                out=np.empty_like(y)
                for i in range(3):
                    out[2*i]=-thickness[i]/k[i]*y[2*i+1]
                    out[2*i+1]=-thickness[i]*k[i]*q*q*y[2*i]+(1. if i==0 else 0.)
                return out
            def bc(left,right):
                return np.array([left[1],right[4],right[0]-left[2],right[1]-left[3],right[2]-left[4],right[3]-left[5]])
            solved=solve_bvp(ode,bc,np.linspace(0,1,30),np.zeros((6,30)),tol=1e-9,max_nodes=10000)
            self.assertTrue(solved.success)
            expected=solved.sol(.5)[0]
            actual=impedance(np.array([q]),a,b,p,88.,14.3)[0]
            self.assertAlmostEqual(actual/expected,1.,places=7)


if __name__=='__main__':unittest.main()
