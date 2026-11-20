import unittest

import numpy as np
from scipy import sparse

from chiplet_floorplanning.placement.microchannels import Channels, CP, RHO, conjugate, hydraulics


class MicrochannelTest(unittest.TestCase):
    def test_two_ports_reverse_without_changing_hydraulic_work(self):
        plate=Channels(count=7,header_side_m=.004)
        q,forward=hydraulics(plate,.001)
        back,reverse=hydraulics(plate,.001,True)
        np.testing.assert_allclose(q,back,rtol=1e-10,atol=0)
        self.assertGreater(np.ptp(q),0.)
        for run in [forward,reverse]:
            self.assertAlmostEqual(run['dissipation_w'],.001,places=11)
            self.assertLess(run['max_path_residual_pa'],1e-6)
            self.assertLess(run['max_node_mass_residual_kg_s'],1e-12)

    def test_heat_only_preheats_downstream_and_conserves_enthalpy(self):
        plate=Channels(count=1,length_m=.012)
        q=np.array([1e-7])
        load=np.array([1.,0.,0.])
        def field(reverse):
            return conjugate(sparse.csr_matrix((3,3)),load,np.arange(3)[None,:],
                             np.linspace(0,plate.length_m,4),np.array([0.,plate.pitch_m]),plate,q,reverse,100.,0.)
        f,rs=field(False)
        b,bs=field(True)
        rise=1/(RHO*CP*q[0])
        np.testing.assert_allclose(f[1:],rise)
        np.testing.assert_allclose(b[1:],0.,atol=1e-12)
        for r in [rs,bs]:
            self.assertAlmostEqual(r['outlet_rise_k'],rise)
