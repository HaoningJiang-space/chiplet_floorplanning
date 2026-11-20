"""Reuse the same rectangle-integration weights across all thermal observation sites."""

import numpy as np
from scipy.sparse import coo_matrix


class FootprintResponse:
    def __init__(self, domain, row):
        d = domain
        dies = np.r_[np.arange(d.problem.count),d.chip]
        centres = np.vstack((d.start.centre_um,d.xy))/1000 - row.origin
        sizes = d.sizes_mm[dies]
        density = d.problem.power_w[dies]/sizes.prod(axis=1)
        n = row.prefix.shape[0]-1
        rows,cols,weights = [],[],[]
        ids = np.arange(len(dies))
        # The rectangle integral is the alternating sum at four corners of
        # the bilinearly interpolated cumulative thermal response.
        for sx,sy in ((1,1),(-1,-1),(1,-1),(-1,1)):
            xy = centres+np.array([sx,sy])*sizes/2
            ij = np.minimum(xy.astype(int),n-1)
            dx,dy = (xy-ij).T
            ix,iy = ij.T
            for x,y,fraction in ((0,0,(1-dx)*(1-dy)),(1,0,dx*(1-dy)),(0,1,(1-dx)*dy),(1,1,dx*dy)):
                rows.append(ids)
                cols.append((iy+y)*(n+1)+ix+x)
                weights.append(sx*sy*density*fraction)
        self.weights = coo_matrix((np.concatenate(weights),(np.concatenate(rows),np.concatenate(cols))),
                                  shape=(len(dies),(n+1)**2)).tocsr()
        self.weights.eliminate_zeros()
        self.chip = d.chip
        self.count = d.problem.count

    def cooling(self,row):
        temperature = self.weights @ row.prefix.ravel()
        return temperature[self.chip]-temperature[self.count:]
