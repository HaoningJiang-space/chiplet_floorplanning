from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.linalg import expm
from scipy.sparse import csr_matrix
from scipy.sparse.linalg import spsolve

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from validation.ttc_spatial import stack, Network, Modal, weights, axis, backward_euler, initialize


class TTCSpatialTest(unittest.TestCase):
    def test_uniform_grid_independent_kronecker_conductance(self):
        dx,dy,dz,k=.002,.003,.004,7.
        g,c,_=stack(np.arange(4)*dx,np.arange(3)*dy,[dz],[k],[1e6],.8,10.)
        lx=np.array([[1,-1,0],[-1,2,-1],[0,-1,1.]])
        ly=np.array([[1,-1],[-1,1.]])
        planar=k*dz*dy/dx*np.kron(np.eye(2),lx)+k*dz*dx/dy*np.kron(ly,np.eye(3))
        contact=2*k*dx*dy/dz
        reference=np.zeros((7,7));reference[:6,:6]=planar+contact*np.eye(6)
        reference[:6,6]=reference[6,:6]=-contact
        reference[6,6]=6*contact+.8
        np.testing.assert_allclose(g.toarray(),reference,atol=1e-15)
        np.testing.assert_allclose(c[:6],1e6*dx*dy*dz)
        self.assertGreater(np.linalg.eigvalsh(reference).min(),0)

    def test_uniform_volumetric_source_converges_to_continuum(self):
        errors=[]
        length,k,area,power,ga=.01,2.,.0001,3.,.2
        for cells in (1,2,4,8):
            g,c,_=stack([0,.01],[0,.01],np.full(cells,length/cells),
                        np.full(cells,k),np.full(cells,1e6),ga,3.)
            source=np.r_[np.full(cells,power/cells),0.]
            steady=spsolve(g,source)
            z=(np.arange(cells)+.5)*length/cells
            exact=power/ga+power/(area*length)*(length**2-z**2)/(2*k)
            errors.append(np.max(abs(steady[:-1]-exact)))
            self.assertAlmostEqual(steady[-1],power/ga,places=10)
        np.testing.assert_allclose(np.array(errors[:-1])/errors[1:],4.,rtol=1e-10)

    def test_modal_chunking_matches_independent_exponential_and_local_balance(self):
        g=csr_matrix([[3.,-1.],[-1.,2.]])
        c=np.array([.03,4.]);b=np.eye(2);h=np.eye(2)
        n=Network(g,c,b,h,{})
        m=Modal(n)
        power=np.array([[1.,0.],[0.,3.],[1.,2.],[0.,0.],[0.,1.]])
        initial=np.array([2.,3.])
        aug=np.zeros((4,4));aug[:2,:2]=-g.toarray()/c[:,None];aug[:2,2:]=np.diag(1/c)
        transition=expm(aug*.1)
        state=initial.copy();expected=[]
        for p in power:
            state=(transition @ np.r_[state,p])[:2];expected.append(state.copy())
        for chunk in (1,3,20):
            actual,ledger=m.run(power,initial,chunk_size=chunk)
            np.testing.assert_allclose(actual,expected,atol=1e-11)
            self.assertTrue(ledger['numerical_energy_screen'])
            self.assertLess(ledger['max_interval_energy_error_j'],1e-12)
        # ODE residual uses independent reconstruction at the final state.
        z=m.w.T @ (c*state)
        derivative=m.w @ (power[-1] @ m.bw-m.rates*z)
        np.testing.assert_allclose(c*derivative+g @ state,power[-1],atol=1e-12)

    def test_backward_euler_time_convergence(self):
        n=Network(csr_matrix([[2.]]),np.array([3.]),np.ones((1,1)),np.ones((1,1)),{})
        exact=2.5*(1-np.exp(-2/3))
        errors=[]
        for count in (10,20,40):
            y=backward_euler(n,np.full((count,1),5.),[0.],1/count)
            errors.append(abs(y[-1,0]-exact))
        self.assertTrue(np.all(np.diff(errors)<0))
        self.assertGreater(errors[-2]/errors[-1],1.9)

    def test_sensor_affine_reconstruction_and_feature_retention(self):
        edges=axis([0,280,1205,1355,2280,2560],500)
        self.assertTrue(all(np.min(abs(edges-v*1e-6))<1e-12 for v in (280,1205,1355,2280)))
        centers=(edges[:-1]+edges[1:])/2
        for location in (650e-6,1280e-6,1900e-6):
            w=weights(centers,location)
            self.assertAlmostEqual(sum(weight for _,weight in w),1.)
            self.assertAlmostEqual(sum((3*centers[i]+7)*weight for i,weight in w),3*location+7)

    def test_conditional_initialization_same_measured_mean(self):
        n=Network(csr_matrix([[2.,-1.],[-1.,2.]]),np.ones(2),np.eye(2),np.eye(2),{})
        for uniform in (False,True):
            initial=initialize(n,np.tile([1.,2.],(12,1)),[5.,7.],uniform)
            self.assertAlmostEqual((n.h @ initial).mean(),6.)

    def test_each_layer_accounts_for_storage_and_interface_flow(self):
        g,c,ids=stack([0,.01],[0,.01],[.001,.002],[5.,2.],[1e6,2e6],.2,3.)
        b=np.array([[1.],[0.],[0.]])
        n=Network(g,c,b,np.eye(3),dict(layer_indices=ids.tolist()))
        y,ledger=Modal(n).run(np.array([[2.],[0.],[1.],[0.]]),np.zeros(3))
        self.assertLess(ledger['max_layer_interval_energy_error_j'],1e-12)
        self.assertGreaterEqual(y.min(),-1e-12)


if __name__=='__main__':
    unittest.main()
