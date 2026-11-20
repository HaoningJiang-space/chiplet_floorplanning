"""Generate two rigid translations from signed thermal responses at limiting cells."""

import numpy as np

from .relocation import ConnectionCost, Landing, legal_destinations
from .search import rotated_size


class JointLandings:
    """Anchor one die, then search the partner's lattice using its remaining thermal margin."""

    def __init__(self, problem, footprint, start, demand, cap, grid_um=1000, gap_um=100):
        self.problem = problem
        self.start = start
        self.cap = cap
        self.gap_um = gap_um
        self.sizes_mm = rotated_size(problem, start.rotation_deg) / 1000
        self.extents = rotated_size(footprint, start.rotation_deg)
        self.net = net = ConnectionCost(problem, start, demand)
        sites = [legal_destinations(footprint, start, c, gap_um, grid_um)
                 for c in range(problem.count)]
        self.xy = np.vstack(sites)
        self.chip = np.repeat(np.arange(problem.count), [len(s) for s in sites])
        self.offset = np.rint((self.xy - start.centre_um[self.chip]) / grid_um).astype(int)
        cuts = np.cumsum([0] + [len(s) for s in sites])
        self.groups = [slice(a, b) for a, b in zip(cuts[:-1], cuts[1:])]
        self.cost = np.concatenate([net.translations(c, s-start.centre_um[c])
                                    for c, s in enumerate(sites)])
        self.radius = 2 * int(abs(self.offset).max(initial=0))
        shifts = np.arange(-self.radius, self.radius+1) * grid_um
        self.links = [[] for _ in sites]
        # The two individual wire costs double-count links joining the moved pair.
        # Tabulate their true Manhattan cost as a function of relative displacement.
        joined = np.sort(net.chips, axis=1)
        for a, b in np.unique(joined, axis=0):
            if a == b:
                continue
            mask = (joined[:, 0] == a) & (joined[:, 1] == b)
            direction = np.where(net.chips[mask, 0] == a, 1, -1)
            vectors = net.vectors[mask] * direction[:, None]
            curve = np.array([abs(shifts[:, None] + axis) @ net.weights[mask] for axis in vectors.T])
            self.links[a].append((b, curve, 1))
            self.links[b].append((a, curve, -1))
        self.headroom = []
        self.cooling = []
        self.last_anchor = {}
        self.retained = set()
        self.retained_partners = {}
        self.scored_pairs = 0

    def observe(self, row):
        """Sample a single adjoint at every old/new source footprint, in kelvin."""
        c = self.chip
        before = row.contribution(self.start.centre_um/1000, self.sizes_mm, self.problem.power_w)
        after = row.contribution(self.xy/1000, self.sizes_mm[c], self.problem.power_w[c])
        self.cooling.append(before[c] - after)
        self.headroom.append(row.headroom_k)

    def partners(self, anchor):
        if anchor in self.retained_partners:
            return self.retained_partners[anchor]
        chip = self.chip[anchor]
        saved = self.last_anchor.get(chip)
        if saved is not None and saved[0] == anchor:
            return saved[1], saved[2]
        offset = self.offset[anchor]
        costs = self.cost + self.cost[anchor] - self.net.initial
        for other, curve, sign in self.links[chip]:
            group = self.groups[other]
            for axis, values in enumerate(curve):
                a = sign * offset[axis]
                b = -sign * self.offset[group, axis]
                r = self.radius
                costs[group] += values[r+a+b] - values[r+a] - values[r+b] + values[r]
        half = (self.extents[chip] + self.extents[self.chip]) / 2
        separated = (abs(self.xy-self.xy[anchor]) >= half+self.gap_um).any(axis=1)
        allowed = np.flatnonzero((self.chip != chip) & separated & (costs <= self.cap + 1e-9))
        feasible_costs = costs[allowed]
        if anchor in self.retained:
            self.retained_partners[anchor] = allowed, feasible_costs
        else:
            self.last_anchor[chip] = anchor, allowed, feasible_costs
        return allowed, feasible_costs

    def best_per_die(self, score):
        solo = np.where(self.cost <= self.cap + 1e-9, score, -np.inf)
        for group in self.groups:
            values = solo[group]
            if not values.size or not np.isfinite(values.max()):
                continue
            ties = np.flatnonzero(values == values.max()) + group.start
            yield int(ties[self.cost[ties].argmin()])

    def retain_contact_landings(self):
        """Keep each die's best landing for each original contact hotspot."""
        for response in self.cooling:
            self.retained.update(self.best_per_die(response))

    def anchors(self):
        solo = np.minimum.reduce([h + c for h, c in zip(self.headroom, self.cooling)])
        return sorted(self.retained.union(self.best_per_die(solo)))

    def propose(self, excluded, incumbent_k):
        """Each anchor can pair with any feasible partner landing on the grid."""
        best = None
        for anchor in self.anchors():
            partners, costs = self.partners(anchor)
            if not len(partners):
                continue
            score = np.minimum.reduce([h + c[anchor] + c[partners]
                                       for h, c in zip(self.headroom, self.cooling)])
            self.scored_pairs += len(partners)
            for i, j in excluded:
                if anchor in (i, j):
                    partner = j if anchor == i else i
                    loc = np.searchsorted(partners, partner)
                    if loc < len(partners) and partners[loc] == partner:
                        score[loc] = -np.inf
            upper = float(score.max())
            if upper < incumbent_k - 1e-8:
                continue
            ties = np.flatnonzero(score == upper)
            local = int(ties[costs[ties].argmin()])
            key = tuple(sorted((anchor, int(partners[local]))))
            rank = (-upper, float(costs[local]), key)
            if best is None or rank < best:
                best = rank
        if best is None:
            return None
        negative_gain, cost, key = best
        return key, self.move(key, cost), -negative_gain

    def move(self, key, cost):
        return Landing(tuple(int(self.chip[i]) for i in key),
                       tuple(tuple(self.xy[i]) for i in key), cost, 0.)
