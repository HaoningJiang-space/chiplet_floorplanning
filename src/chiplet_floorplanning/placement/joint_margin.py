"""Choose both chiplets and both destinations by maximizing the minimum observed thermal margin."""

import numpy as np


class PairMargin:
    """An exact two-move solver on the static single-die landing lattice."""

    def __init__(self, domain, block_size=32):
        self.d = d = domain
        self.block_size = block_size
        self.blocks_scored = self.pairs_scored = 0
        starts, ends = [], []
        for group in d.groups:
            for i in range(group.start, group.stop, block_size):
                starts.append(i)
                ends.append(min(i+block_size, group.stop))
        self.starts = np.array(starts, dtype=int)
        self.ends = np.array(ends, dtype=int)
        if not starts:
            self.left = self.right = np.empty(0, dtype=int)
            return
        dies = d.chip[self.starts]
        left, right = np.triu_indices(len(starts), 1)
        a, b = dies[left], dies[right]
        # Feasibility lower bound for a pair of blocks. Shared links can undo at
        # most twice their weight times the smaller endpoint displacement per axis.
        n = d.problem.count
        shared = np.zeros((n,n))
        np.add.at(shared, tuple(np.sort(d.net.chips, axis=1).T), d.net.weights)
        displacement = abs(d.xy-d.start.centre_um[d.chip])
        maximum = np.maximum.reduceat(displacement, self.starts, axis=0)
        costs = np.minimum.reduceat(d.cost, self.starts)
        correction = 2*shared[a,b]*np.minimum(maximum[left], maximum[right]).sum(axis=1)
        low, high = (f.reduceat(d.xy,self.starts,axis=0) for f in (np.minimum,np.maximum))
        far = np.maximum(high[left]-low[right], high[right]-low[left])
        feasible = ((a != b) & (costs[left]+costs[right]-d.net.initial-correction <= d.cap+1e-9)
                    & (far >= (d.extents[a]+d.extents[b])/2+d.gap_um).any(axis=1))
        self.left, self.right = left[feasible], right[feasible]
        self.link_id = np.zeros((n,n), dtype=int)
        curves = [np.zeros((2, 2*d.radius+1))]
        for i, links in enumerate(d.links):
            for j, curve, sign in links:
                if sign == 1:
                    self.link_id[i,j] = len(curves)
                    curves.append(curve)
        self.curves = np.stack(curves)

    def endpoints(self, blocks):
        sites = self.starts[blocks,None] + np.arange(self.block_size)
        return np.minimum(sites, self.ends[blocks,None]-1)

    def feasible_pairs(self, blocks):
        d = self.d
        i = self.endpoints(self.left[blocks])[:,:,None]
        j = self.endpoints(self.right[blocks])[:,None,:]
        a, b = d.chip[i], d.chip[j]
        half = (d.extents[a]+d.extents[b])/2 + d.gap_um
        valid = (abs(d.xy[i]-d.xy[j]) >= half).any(axis=-1)
        costs = d.cost[i] + d.cost[j] - d.net.initial
        links = self.link_id[a,b]
        for axis in (0,1):
            u, v = d.offset[i,axis], -d.offset[j,axis]
            f = self.curves[:,axis]
            r = d.radius
            costs += f[links,r+u+v] - f[links,r+u] - f[links,r+v] + f[links,r]
        valid &= costs <= d.cap+1e-9
        # Omit the padding on the last block of each die.
        valid &= (self.starts[self.left[blocks],None,None]+np.arange(self.block_size)[None,:,None]
                  < self.ends[self.left[blocks],None,None])
        valid &= (self.starts[self.right[blocks],None,None]+np.arange(self.block_size)[None,None,:]
                  < self.ends[self.right[blocks],None,None])
        batch, x, y = np.nonzero(valid)
        return i[batch,x,0], j[batch,0,y], costs[batch,x,y]

    def propose(self, excluded):
        d = self.d
        if not len(self.left):
            return None
        # Each witness can choose its own best site in a block. This relaxation
        # overestimates what one actual pair can simultaneously achieve.
        upper = np.full(len(self.left), np.inf)
        for h, c in zip(d.headroom, d.cooling):
            maximum = np.maximum.reduceat(c, self.starts)
            upper = np.minimum(upper, h+maximum[self.left]+maximum[self.right])
        order = np.argsort(-upper, kind="stable")
        best = None
        for begin in range(0, len(order), 16):
            blocks = order[begin:begin+16]
            if best is not None:
                blocks = blocks[upper[blocks] >= -best[0]-1e-10]
            if not len(blocks):
                break
            self.blocks_scored += len(blocks)
            i, j, costs = self.feasible_pairs(blocks)
            if not len(i):
                continue
            self.pairs_scored += len(i)
            score = np.full(len(i), np.inf)
            for h, c in zip(d.headroom, d.cooling):
                np.minimum(score, h+c[i]+c[j], out=score)
            for a, b in excluded:
                score[(i==a) & (j==b)] = -np.inf
            value = score.max()
            if not np.isfinite(value):
                continue
            tied = np.flatnonzero(score == value)
            k = tied[np.lexsort((j[tied],i[tied],costs[tied]))[0]]
            rank = (-float(value), float(costs[k]), (int(i[k]),int(j[k])))
            if best is None or rank < best:
                best = rank
        if best is not None:
            minus, cost, key = best
            return key, d.move(key,cost), -minus
