"""Search methods under one exact-FV budget, for paired comparisons.

Budget unit: distinct FV solves, including the shared start set. Length is the
exact two-pin lower bound and costs no solve; every method may use it freely.
Each evaluated layout records the cumulative solves at its evaluation, so
anytime curves come from the same run. A duplicate layout costs nothing and is
looked up; a layout sharing an already-solved thermal problem costs no solve.
A round makes progress only if it adds an FV solve or a layout whose (length,
peak) is not weakly dominated by any earlier layout; new layouts that merely
repeat known objectives (e.g. thermally equivalent orientations) do not count.
Every method stops after `stall_rounds` rounds without progress, or after
`max_rounds` rounds in total; `Run.stop_reason` records 'budget', 'stalled',
'round_cap' or 'sampler_failed' (random search only).
"""
import numpy as np

from .evaluate import pareto_front, sample_legal, thermal_key
from .lp import TopologyLP
from .search import layout_key, length_descent, mutate


class Run:
    def __init__(self, evaluator, fv_solves, stall_rounds=20, max_rounds=2000):
        self.evaluator, self.limit = evaluator, fv_solves
        self.stall_rounds, self.max_rounds = stall_rounds, max_rounds
        self.layouts, self.lengths, self.peaks, self.cost = [], [], [], []
        self.die_peaks, self.max_nets = [], []  # local view: per-die peaks (degC), longest net (mm)
        self.index = {}
        self.rounds, self.stale, self.stop_reason = 0, 0, None
        self._solves_seen = evaluator.solves

    @property
    def exhausted(self):
        return self.evaluator.solves >= self.limit

    def _improved(self, before):
        """Some layout added since row `before` is not weakly dominated by any earlier layout."""
        if before == 0 or len(self.layouts) == before:
            return len(self.layouts) > before
        length, peak = np.array(self.lengths), np.array(self.peaks)
        old_l, old_p = length[:before], peak[:before]
        new_l, new_p = length[before:], peak[before:]
        covered = ((old_l[None] <= new_l[:, None]) & (old_p[None] <= new_p[:, None])).any(axis=1)
        return bool((~covered).any())

    def keep_going(self, before):
        """Count one proposal round that started at row `before`; False once the run must stop."""
        self.rounds += 1
        progress = self.evaluator.solves > self._solves_seen or self._improved(before)
        self._solves_seen = self.evaluator.solves
        self.stale = 0 if progress else self.stale + 1
        if self.exhausted:
            self.stop_reason = "budget"
        elif self.stale >= self.stall_rounds:
            self.stop_reason = "stalled"
        elif self.rounds >= self.max_rounds:
            self.stop_reason = "round_cap"
        return self.stop_reason is None

    def finish(self):
        if self.stop_reason is None:
            self.stop_reason = "budget" if self.exhausted else "stalled"

    def restart(self):
        """Clear the stall state before a new phase (e.g. the next epsilon cap)."""
        self.stale, self.stop_reason = 0, None

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
            self.die_peaks += list(self.evaluator.die_peaks_c(new))  # cached: no extra solve
            self.max_nets += [self.evaluator.max_net_mm(layout) for layout in new]
            for layout, peak in zip(new, peaks):
                self.index[layout_key(layout)] = len(self.layouts)
                self.layouts.append(layout)
                self.lengths.append(self.evaluator.length_m(layout))
                self.peaks.append(float(peak))
                self.cost.append(self.evaluator.solves)
        return [self.index.get(layout_key(layout)) for layout in candidates]

    def arrays(self):
        return np.array(self.lengths), np.array(self.peaks), np.array(self.cost)

    def local(self):
        """Per-die peaks (n_layouts, n_dies) in degC and the longest single net per layout in mm."""
        return np.array(self.die_peaks), np.array(self.max_nets)


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
    """Generations until the budget is spent or proposal rounds stall."""
    while not run.exhausted:
        before = len(run.layouts)
        candidates = propose()
        if run.stop_reason:
            break
        if candidates:
            run.evaluate(candidates)
        if not run.keep_going(before):
            break
    run.finish()


def random_search(run, initial, rng, batch=96, **_):
    """Independent legal samples (sequential constructive sampler)."""
    problem, gap_um = run.evaluator.problem, run.evaluator.gap_um
    run.evaluate(initial)

    def propose():
        try:
            return [sample_legal(problem, gap_um, rng) for _ in range(batch)]
        except RuntimeError:
            run.stop_reason = "sampler_failed"  # keep the evaluated rows; the sampler cannot fill this case
            return []
    _loop(run, propose)


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
        run.evaluate(propose())
        if not run.keep_going(before):
            break
        if len(run.layouts) == before:
            continue
        pool = population + list(range(before, len(run.layouts)))
        length, peak, _ = run.arrays()
        rank, crowd = ranks_and_crowding(length[pool], peak[pool])
        keep = np.lexsort((-crowd, rank))[:batch]
        population = [pool[k] for k in keep]
    run.finish()


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
        if not run.keep_going(before):
            break
        length, peak, _ = run.arrays()
        for c, (w, row) in enumerate(zip(weights, rows)):
            if row is not None:
                delta = score(row, w) - score(state[c], w)
                if delta <= 0 or rng.random() < np.exp(-delta/tau):
                    state[c] = row
    run.finish()


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
        run.restart()
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
    run.stop_reason = None
    run.finish()


def _sweep(args):
    problem, layout, gap_um, pairs, levels = args
    return TopologyLP(problem, layout, gap_um, pairs).sweep(levels)


def topology_lp(run, initial, rng, batch=96, levels=6, pairs=10, explore=0.5, **_):
    """Archive parents (optionally mutated to a new topology) polished by topology LP sweeps.

    Each parent's side relations and rotations define an LP; layouts along
    min L s.t. linearised hot-pair separation >= D are evaluated with FV.
    Sweeps run in the evaluator's process pool; LP time uses no FV solve.
    """
    problem, gap_um = run.evaluator.problem, run.evaluator.gap_um
    run.evaluate(initial)

    def propose():
        archive = pareto_front(*run.arrays()[:2])
        parents = []
        for _ in range(-(-batch//levels)):
            parent = run.layouts[archive[rng.integers(len(archive))]]
            if rng.random() < explore:
                parent = mutate(problem, parent, rng, gap_um) or parent
            parents.append((problem, parent, gap_um, pairs, levels))
        pool = run.evaluator.pool
        swept = pool.map(_sweep, parents) if pool else map(_sweep, parents)
        return [c for group in swept for c in group if layout_key(c) not in run.index][:batch]
    _loop(run, propose)


METHODS = dict(random=random_search, pareto_ls=pareto_local_search, nsga=nsga_mutation,
               annealing=annealing, epsilon=epsilon_search, topology_lp=topology_lp)
