"""Small-instance simultaneous assignment of any number of die translations."""

from time import perf_counter

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix

from .relocation import Landing


class JointAssignment:
    """Use one binary per possible landing. A die with no selected site stays put."""

    def __init__(self, domain, minimum_moves, maximum_moves, time_limit_s=None):
        self.d = d = domain
        self.time_limit_s = time_limit_s
        self.incomplete = False
        self.dual_upper_k = None
        n = len(d.xy)
        self.rows, self.limits = [], []
        self.wire_cuts = 0
        for group in d.groups:
            row = np.zeros(n)
            row[group] = 1.
            self.add_row(row, 1.)
        self.add_row(np.ones(n), maximum_moves)
        self.add_row(-np.ones(n), -minimum_moves)
        for i in range(n):
            js = np.arange(i+1,n)
            half = (d.extents[d.chip[i]]+d.extents[d.chip[js]])/2 + d.gap_um
            conflict = (d.chip[i] != d.chip[js]) & (abs(d.xy[i]-d.xy[js]) < half).all(axis=1)
            for j in js[conflict]:
                row = np.zeros(n)
                row[[i,j]] = 1.
                self.add_row(row, 1.)

    def add_row(self, row, limit):
        self.rows.append(row)
        self.limits.append(limit)

    def propose(self, excluded):
        d = self.d
        n = len(d.xy)
        offsets = d.xy - d.start.centre_um[d.chip]
        then = perf_counter()
        while True:
            rows = list(self.rows)
            limits = list(self.limits)
            for key in excluded:
                row = -np.ones(n)
                row[list(key)] = 1.
                rows.append(row)
                limits.append(len(key)-1)
            constraints = np.zeros((len(rows)+len(d.cooling), n+1))
            constraints[:len(rows),:n] = rows
            constraints[len(rows):,:n] = -np.asarray(d.cooling)
            constraints[len(rows):,-1] = 1.
            options = {"mip_rel_gap":0.}
            if self.time_limit_s is not None:
                remaining = self.time_limit_s - (perf_counter()-then)
                if remaining <= 0:
                    self.incomplete = True
                    return None
                options["time_limit"] = remaining
            result = milp(np.r_[np.zeros(n),-1.], integrality=np.r_[np.ones(n),0],
                          bounds=Bounds(np.r_[np.zeros(n),-np.inf], np.r_[np.ones(n),np.inf]),
                          constraints=LinearConstraint(csr_matrix(constraints), -np.inf, limits+d.headroom),
                          options=options)
            if result.status == 2:
                return None
            if result.status == 1 and result.x is None:
                self.incomplete = True
                return None
            if not result.success and result.status != 1:
                raise RuntimeError(result.message)
            key = tuple(map(int,np.flatnonzero(result.x[:n]>.5)))
            chips = d.chip[list(key)]
            delta = np.zeros_like(d.start.centre_um)
            delta[chips] = offsets[list(key)]
            cost = d.net.shifted(delta)
            if cost <= d.cap + 1e-9:
                self.dual_upper_k = float(-result.mip_dual_bound) if result.mip_dual_bound is not None else np.inf
                self.incomplete |= not result.success
                move = Landing(tuple(map(int,chips)),tuple(map(tuple,d.xy[list(key)])),cost,0.)
                score = min(h+c[list(key)].sum() for h,c in zip(d.headroom,d.cooling))
                return key, move, float(score)
            # A supporting plane of the convex pin Manhattan cost removes this
            # over-budget choice without removing any feasible assignment.
            i,j = d.net.chips.T
            signs = np.sign(d.net.vectors + delta[i]-delta[j])*d.net.weights[:,None]
            gradient = np.zeros_like(delta)
            np.add.at(gradient,i,signs)
            np.add.at(gradient,j,-signs)
            coeff = (gradient[d.chip]*offsets).sum(axis=1)
            limit = d.cap-cost+float((gradient*delta).sum())
            # Normalize so a geometric wire violation is well above MILP feasibility noise.
            scale = 1. / max(1e-12, abs(coeff).max(), abs(limit))
            self.add_row(coeff*scale, limit*scale)
            # The solver may accept a near-boundary assignment within its own
            # feasibility tolerance. Exclude this verified wire violation exactly.
            no_good = -np.ones(n)
            no_good[list(key)] = 1.
            self.add_row(no_good,len(key)-1)
            self.wire_cuts += 1
