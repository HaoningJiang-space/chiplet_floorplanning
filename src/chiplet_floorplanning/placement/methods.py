"""Search methods under one exact-FV budget, for paired comparisons.

Budget unit: distinct FV solves, including the shared start set. Length is the
exact two-pin lower bound and costs no solve; every method may use it freely.
Each evaluated layout records the cumulative solves at its evaluation, so
anytime curves come from the same run. A duplicate layout costs nothing and is
looked up; a layout sharing an already-solved thermal problem costs no solve.
"""
import numpy as np

from .evaluate import pareto_front, sample_legal, thermal_key
from .search import layout_key, length_descent, mutate


class Run:
    def __init__(self, evaluator, fv_solves):
        self.evaluator, self.limit = evaluator, fv_solves
        self.layouts, self.lengths, self.peaks, self.cost = [], [], [], []
        self.index = {}

    @property
    def exhausted(self):
        return self.evaluator.solves >= self.limit

    def evaluate(self, candidates):
        """Evaluate within budget; returns each candidate's row index or None if over budget."""
        new, keys, pending = [], set(), set()
        for layout in candidates:
            key = layout_key(layout)
            if key in self.index or key in keys:
                continue
            thermal = thermal_key(self.evaluator.problem, layout)
            fresh = thermal not in self.evaluator.cache and thermal not in pending
            if fresh:
                if self.evaluator.solves + len(pending) >= self.limit:
                    continue
                pending.add(thermal)
            keys.add(key)
            new.append(layout)
        if new:
            peaks = self.evaluator.peaks_c(new)
            for layout, peak in zip(new, peaks):
                self.index[layout_key(layout)] = len(self.layouts)
                self.layouts.append(layout)
                self.lengths.append(self.evaluator.length_m(layout))
                self.peaks.append(float(peak))
                self.cost.append(self.evaluator.solves)
        return [self.index.get(layout_key(layout)) for layout in candidates]

    def arrays(self):
        return np.array(self.lengths), np.array(self.peaks), np.array(self.cost)


def _children(run, parents, rng, batch, max_moves, accept=None):
    """Mutate parents with 1..max_moves legal moves; drop seen layouts and rejects."""
    problem, gap_um = run.evaluator.problem, run.evaluator.gap_um
    children = []
    for _ in range(50*batch):
        if len(children) >= batch:
            break
        child = run.layouts[parents[rng.integers(len(parents))]]
        for _ in range(int(rng.integers(1, max_moves + 1))):
            moved = mutate(problem, child, rng, gap_um)
            child = moved if moved is not None else child
        if layout_key(child) in run.index or (accept and not accept(child)):
            continue
        children.append(child)
    return children


def _loop(run, propose):
    """Generations until the budget is spent or proposals stop adding rows."""
    stale = 0
    while not run.exhausted and stale < 3:
        before = len(run.layouts)
        candidates = propose()
        if candidates:
            run.evaluate(candidates)
        stale = stale + 1 if len(run.layouts) == before else 0


def random_search(run, initial, rng, batch=96, **_):
    """Independent legal samples (sequential constructive sampler)."""
    problem, gap_um = run.evaluator.problem, run.evaluator.gap_um
    run.evaluate(initial)
    _loop(run, lambda: [sample_legal(problem, gap_um, rng) for _ in range(batch)])


def pareto_local_search(run, initial, rng, batch=96, max_moves=3, **_):
    """Mutate uniformly chosen members of the current (length, peak) archive."""
    run.evaluate(initial)
    _loop(run, lambda: _children(run, pareto_front(*run.arrays()[:2]), rng, batch, max_moves))


def ranks_and_crowding(length, peak):
    """Non-dominated sorting ranks and crowding distances (both objectives minimised)."""
    n = len(length)
    dominated = ((length[:, None] <= length[None]) & (peak[:, None] <= peak[None])
                 & ((length[:, None] < length[None]) | (peak[:, None] < peak[None])))
    count = dominated.sum(axis=0)
    rank = np.full(n, -1)
    level, current = 0, np.flatnonzero(count == 0)
    while current.size:
        rank[current] = level
        count = count - dominated[current].sum(axis=0)
        count[rank >= 0] = -1
        current = np.flatnonzero(count == 0)
        level += 1
    crowd = np.zeros(n)
    for r in range(level):
        members = np.flatnonzero(rank == r)
        for values in (length, peak):
            order = members[np.argsort(values[members], kind="stable")]
            span = values[order[-1]] - values[order[0]]
            crowd[order[[0, -1]]] = np.inf
            if span > 0 and len(order) > 2:
                crowd[order[1:-1]] += (values[order[2:]] - values[order[:-2]])/span
    return rank, crowd


def nsga_mutation(run, initial, rng, batch=96, max_moves=3, **_):
    """NSGA-II selection (rank, crowding, binary tournaments) with legal mutation only."""
    population = [i for i in run.evaluate(initial) if i is not None]

    def propose():
        length, peak, _ = run.arrays()
        rank, crowd = ranks_and_crowding(length[population], peak[population])
        parents = []
        for _ in range(batch):
            a, b = rng.integers(len(population), size=2)
            better = a if (rank[a], -crowd[a]) < (rank[b], -crowd[b]) else b
            parents.append(population[better])
        return _children(run, parents, rng, batch, max_moves)

    while not run.exhausted:
        before = len(run.layouts)
        candidates = propose()
        run.evaluate(candidates)
        if len(run.layouts) == before:
            break
        pool = population + list(range(before, len(run.layouts)))
        length, peak, _ = run.arrays()
        rank, crowd = ranks_and_crowding(length[pool], peak[pool])
        keep = np.lexsort((-crowd, rank))[:batch]
        population = [pool[k] for k in keep]


def annealing(run, initial, rng, batch=96, max_moves=3, t_start=1.0, t_end=0.01, **_):
    """Parallel Metropolis chains on normalised T + w L, weights log-spaced over 10^±1.5.

    Units: both objectives are scaled by the start set's spread, so the weight
    and annealing temperature are dimensionless.
    """
    problem, gap_um = run.evaluator.problem, run.evaluator.gap_um
    rows = [i for i in run.evaluate(initial) if i is not None]
    length, peak, _ = run.arrays()
    dl, dt = max(np.std(length[rows]), 1e-9), max(np.std(peak[rows]), 1e-9)
    weights = np.logspace(-1.5, 1.5, batch)
    score = lambda i, w: peak[i]/dt + w*length[i]/dl
    state = [min(rows, key=lambda i: score(i, w)) for w in weights]
    start = run.evaluator.solves
    while not run.exhausted:
        progress = (run.evaluator.solves - start)/max(1, run.limit - start)
        tau = t_start*(t_end/t_start)**progress
        proposals = []
        for current in state:
            child = run.layouts[current]
            for _ in range(int(rng.integers(1, max_moves + 1))):
                moved = mutate(problem, child, rng, gap_um)
                child = moved if moved is not None else child
            proposals.append(child)
        before = len(run.layouts)
        rows = run.evaluate(proposals)
        if len(run.layouts) == before and all(r is None or r == s for r, s in zip(rows, state)):
            break
        length, peak, _ = run.arrays()
        for c, (w, row) in enumerate(zip(weights, rows)):
            if row is not None:
                delta = score(row, w) - score(state[c], w)
                if delta <= 0 or rng.random() < np.exp(-delta/tau):
                    state[c] = row


def epsilon_search(run, initial, rng, batch=96, max_moves=3, length_caps_m=(), parents=8, **_):
    """Directly optimise the main metric: coolest layout with L <= cap, budget split over caps.

    Length is checked before any FV solve; starts that exceed a cap are first
    moved below it by exact length descent (no thermal cost).
    """
    problem, gap_um = run.evaluator.problem, run.evaluator.gap_um
    run.evaluate(initial)
    total = run.limit
    caps = sorted(length_caps_m)
    for j, cap in enumerate(caps):
        run.limit = run.evaluator.solves + (total - run.evaluator.solves)//(len(caps) - j)
        feasible = lambda layout: run.evaluator.length_m(layout) <= cap
        length, peak, _ = run.arrays()
        if not (length <= cap).any():
            descended = [length_descent(problem, run.layouts[i], rng, gap_um)
                         for i in np.argsort(length)[:batch]]
            run.evaluate([d for d in descended if feasible(d)])

        def propose():
            length, peak, _ = run.arrays()
            ok = np.flatnonzero(length <= cap)
            if not ok.size:
                return []
            best = ok[np.argsort(peak[ok])[:parents]]
            return _children(run, list(best), rng, batch, max_moves, accept=feasible)
        _loop(run, propose)
    run.limit = total


METHODS = dict(random=random_search, pareto_ls=pareto_local_search, nsga=nsga_mutation,
               annealing=annealing, epsilon=epsilon_search)
