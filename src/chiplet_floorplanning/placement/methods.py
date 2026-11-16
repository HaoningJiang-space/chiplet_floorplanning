"""Search methods under one exact-FV budget, for paired comparisons.

Budget unit: distinct FV solves, including the shared start set. Length is the
exact two-pin lower bound and costs no solve; every method may use it freely.
Each evaluated layout records the cumulative solves at its evaluation, so
anytime curves come from the same run. A duplicate layout costs nothing and is
looked up; a layout sharing an already-solved thermal problem costs no solve.
A round makes progress only if it adds a new thermal state or a layout whose (length,
peak) is not weakly dominated by any earlier layout; new layouts that merely
repeat known objectives (e.g. thermally equivalent orientations) do not count.
Every method stops after `stall_rounds` rounds without progress, or after
`max_rounds` rounds in total; `Run.stop_reason` records 'budget', 'stalled',
'round_cap' or 'sampler_failed' (random search only).
"""
import numpy as np

from .evaluate import pareto_front, sample_legal, thermal_key
from .geometry import pin_manhattan_um
from .lp import TopologyLP, centre_relations, hotspot_move, legalize_relations, length_anneal, milp_relations, slp_chain
from .thermal_milp import ThermalTable
from .search import layout_key, length_descent, mutate


class Run:
    def __init__(self, evaluator, fv_solves, stall_rounds=20, max_rounds=2000):
        self.evaluator, self.limit = evaluator, fv_solves
        self.stall_rounds, self.max_rounds = stall_rounds, max_rounds
        self.layouts, self.lengths, self.peaks, self.cost = [], [], [], []
        self.die_peaks, self.max_nets = [], []  # local view: per-die peaks (degC), longest net (mm)
        self.index = {}
        self.rounds, self.stale, self.stop_reason = 0, 0, None
        self._states_seen = len(evaluator.cache)
        self.notes = {}   # method diagnostics kept in the run summary

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
        # Progress is a new distinct thermal state or a front improvement; repeated factorisations (charged
        # to the budget by topology_slp) are spending, not progress.
        progress = len(self.evaluator.cache) > self._states_seen or self._improved(before)
        self._states_seen = len(self.evaluator.cache)
        self.stale = 0 if progress else self.stale + 1
        if self.exhausted:
            self.stop_reason = "budget"
        elif self.stale >= self.stall_rounds:
            self.stop_reason = "stalled"
        elif self.rounds >= self.max_rounds:
            self.stop_reason = "round_cap"
        return self.stop_reason is None

    @property
    def out_of_rounds(self):
        return self.rounds >= self.max_rounds

    def finish(self):
        if self.stop_reason is None:
            self.stop_reason = "budget" if self.exhausted else "round_cap" if self.out_of_rounds else "stalled"

    def restart(self):
        """Clear the phase's stop state before a new phase (e.g. the next epsilon cap).
        The round cap is global: callers check `out_of_rounds` before starting a phase."""
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
        if run.out_of_rounds:
            break
        feasible = lambda layout: run.evaluator.length_m(layout) <= cap
        length, peak, _ = run.arrays()
        if not (length <= cap).any():
            descended = [length_descent(problem, run.layouts[i], rng, gap_um, cost=run.evaluator.length_m)
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
    run.stop_reason = None  # a per-cap budget is not the run's budget; finish() judges the whole run
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


def lp_then_epsilon(run, initial, rng, lp_share=0.5, **kw):
    """topology_lp on the first `lp_share` of the budget, then epsilon from every layout found so far."""
    total = run.limit
    run.evaluate(initial)  # the shared start set is charged before the split
    run.limit = max(run.evaluator.solves, int(lp_share*total))
    topology_lp(run, [], rng, **kw)
    run.limit = total
    run.restart()
    if run.out_of_rounds:
        run.finish()
        return
    epsilon_search(run, [], rng, **kw)


def slp_job_key(problem, start, goal, mode):
    """Identity of an SLP chain: the thermal state alone is not enough, because rotations that leave the
    occupied boxes unchanged (e.g. a half turn) still move the pins and so change the length LP."""
    return thermal_key(problem, start), start.rotation_deg.astype(np.int16).tobytes(), round(float(goal), 6), mode


def topology_slp(run, initial, rng, lp_share=0.5, caps=8, steps=8, explore=0.5, targets='peak', hotspot=0.0,
                 **kw):
    """topology_lp explores topologies on the first `lp_share` of the budget; then trust-region SLP chains
    (`slp_chain`) polish archive layouts under `caps` die-peak caps spread over the archive's peak range.

    Each round starts one chain per cap from the shortest archive layout under the cap and one from the
    longest layout above it (optionally first moved to a new topology). With targets 'length' (or 'both') the
    chains instead (also) hold length budgets spread over the archive's length range and minimise the peak,
    starting from the coolest layout within the budget and the coolest one over it. With probability
    `hotspot` a start is first changed by `hotspot_move` (aimed at its hottest die) instead of a random
    move. A chain makes at most steps + 1 LU
    factorisations (its start plus one per step), so before dispatch the number of chains and their steps are
    cut until that worst case fits the remaining budget; every factorisation a chain made is then charged,
    including its start and any repeat of a cached layout. New results are cached, so `run.evaluate` records
    the layouts without solving again.
    """
    problem, gap_um, evaluator = run.evaluator.problem, run.evaluator.gap_um, run.evaluator
    if evaluator.modes is not None:
        raise ValueError("topology_slp optimises nominal die peaks; multi-mode evaluators are not supported")
    total = run.limit
    run.evaluate(initial)
    run.limit = max(evaluator.solves, int(lp_share*total))
    topology_lp(run, [], rng, explore=explore, **kw)
    run.limit = total
    run.restart()
    if run.out_of_rounds:
        run.finish()
        return

    tried = set()   # (start, cap) pairs already polished: re-running one would only re-spend its solves

    def propose():
        length, peak, _ = run.arrays()
        die_peaks, _ = run.local()
        archive = np.asarray(pareto_front(length, peak))
        quantiles = np.linspace(0, 1, caps + 2)[1:-1]
        goals = []
        if targets in ("peak", "both"):
            for cap in np.quantile(peak[archive], quantiles):
                under, over = archive[peak[archive] <= cap], archive[peak[archive] > cap]
                starts = [under[np.argmin(length[under])]] if under.size else []
                starts += [over[np.argmax(length[over])]] if over.size else []
                goals += [(s, float(cap), "peak") for s in starts]
        if targets in ("length", "both"):
            for budget in np.quantile(length[archive], quantiles):
                within, over = archive[length[archive] <= budget], archive[length[archive] > budget]
                starts = [within[np.argmin(peak[within])]] if within.size else []
                starts += [over[np.argmin(peak[over])]] if over.size else []
                goals += [(s, float(budget), "length") for s in starts]
        pending = {}
        for s, goal, mode in goals:
            start = run.layouts[s]
            if rng.random() < hotspot:
                start = hotspot_move(problem, start, die_peaks[s], rng, gap_um) or start
            elif rng.random() < explore:
                start = mutate(problem, start, rng, gap_um) or start
            key = slp_job_key(problem, start, goal, mode)
            if key not in tried and key not in pending:
                pending[key] = (problem, start, gap_um, evaluator.resolution, goal, steps, mode)
        room = run.limit - evaluator.solves
        if room < 2 or not pending:    # a chain needs its start and at least one step
            return []
        keys = list(pending)[:room//2]
        tried.update(keys)             # only dispatched chains count as tried; the rest stay eligible
        chain_steps = min(steps, room//len(keys) - 1)   # worst case len(keys)*(chain_steps + 1) <= room
        jobs = [pending[k][:5] + (chain_steps, pending[k][6]) for k in keys]
        chains = evaluator.pool.map(slp_chain, jobs) if evaluator.pool else map(slp_chain, jobs)
        found = []
        for chain in chains:
            for layout, die_peaks in chain:
                evaluator.solves += 1   # every factorisation the chain made, cached or not
                key = thermal_key(problem, layout)
                if key not in evaluator.cache:
                    evaluator.cache[key] = np.r_[die_peaks.max(), die_peaks]
                found.append(layout)
        return [c for c in found if layout_key(c) not in run.index]
    _loop(run, propose)


def shortest_seeds(problem, gap_um, initial, pool, milp_s=120.0, steps=1000, chains=8, seed=0):
    """Short-end seeds with no FV cost: MILP rotations/relations finished by the exact relation LP, then
    length annealing chains from it and from the shortest start. Returns the distinct legal results."""
    length = lambda l: float(pin_manhattan_um(problem, l).sum())/1e6
    starts = [min(initial, key=length)] if initial else []
    found = milp_relations(problem, gap_um, milp_s)
    if found is not None:
        lp = TopologyLP(problem, found, gap_um, pairs=0, relations=centre_relations(problem, found, gap_um))
        x = lp._solve(lp.length)
        exact = lp._layout(x) if x is not None else None
        starts += [exact] if exact is not None else []
    if not starts:
        return []
    jobs = [(problem, starts[k % len(starts)], gap_um, seed*1000 + k, steps, 0.02*length(starts[k % len(starts)]),
             0.0002*length(starts[k % len(starts)])) for k in range(chains)]
    results = pool.map(length_anneal, jobs) if pool else map(length_anneal, jobs)
    return starts + [layout for layout, _ in results]


def relation_space(run, initial, rng, milp_s=120.0, anneal_steps=1000, chains=8, **kw):
    """The full method: short-end seeds (`shortest_seeds`, no FV), then `topology_slp` from all starts."""
    evaluator = run.evaluator
    seeds = shortest_seeds(evaluator.problem, evaluator.gap_um, list(initial), evaluator.pool, milp_s, anneal_steps,
                           chains, int(rng.integers(1 << 30)))
    if not initial and not seeds:
        raise RuntimeError('no legal start: no initial layouts and the MILP found no layout')
    topology_slp(run, list(initial) + seeds, rng, **kw)


def thermal_space(run, initial, rng, milp_s=120.0, anneal_steps=1000, chains=8, grid=6, levels=4, cap_milp_s=60.0,
                  refine=0, calibrate=0, **kw):
    """relation_space with the grid-kernel temperature in the MILP (plan: docs/thermal-milp-plan.md).

    After the short-end seeds, a ThermalTable is built (its lone-die FV solves are charged to the budget); one MILP
    minimises the kernel peak, then `levels` caps evenly between that and the shortest seed's kernel peak each give
    a wirelength-minimal layout under the cap. With `refine` > 0 each of these solves is repeated up to `refine`
    times after splitting the cells around its result (adaptive grid), while the new kernel solves fit the budget.
    With `calibrate` > 0 the caps are FV targets instead: evenly between the FV peaks of the coolest MILP result
    and the shortest seed, each first mapped to a kernel cap with the kernel's overestimate on the coolest result,
    then corrected `calibrate` times by the FV miss of the previous solve (cap += target - FV peak).
    Each result is legalised with minimal displacement, FV-confirmed, and all of them join the starts of
    `topology_slp`.
    """
    evaluator = run.evaluator
    problem, gap_um = evaluator.problem, evaluator.gap_um
    seeds = shortest_seeds(problem, gap_um, list(initial), evaluator.pool, milp_s, anneal_steps, chains,
                           int(rng.integers(1 << 30)))
    starts = list(initial) + seeds
    if not starts:
        raise RuntimeError('no legal start: no initial layouts and the MILP found no layout')
    table = ThermalTable(problem, gap_um, grid, evaluator.resolution)
    notes = run.notes.setdefault('thermal_milp', dict(grid=grid, refine=refine, kernel_solves=0, results=[]))
    reserve = levels*(calibrate + 1) + 2       # FV confirmations of the MILP results and of the shortest seed

    def fits(pending):
        return pending + reserve <= run.limit - evaluator.solves

    def charge():
        notes['kernel_solves'] += table.solves
        evaluator.solves += table.solves
        table.build(evaluator.pool)

    if not fits(table.solves):
        notes['skipped'] = 'kernel solves do not fit the remaining FV budget'
        topology_slp(run, starts, rng, **kw)
        return
    charge()

    def solve(cap):
        layout = milp_relations(problem, gap_um, cap_milp_s, thermal=(table, cap))
        for _ in range(refine):
            if layout is None or not fits(table.refine(layout)):
                break
            charge()
            layout = milp_relations(problem, gap_um, cap_milp_s, thermal=(table, cap)) or layout
        return layout

    candidates = []

    def confirm(cap, layout, target=None):
        """Legalise, record and FV-confirm one MILP result; returns (legal layout or None, FV peak or None)."""
        legal = legalize_relations(problem, layout, gap_um) if layout is not None else None
        row = dict(cap_c=cap, target_c=target, solved=layout is not None, legal=legal is not None)
        fv = None
        if legal is not None:
            candidates.append(legal)
            row['kernel_peak_c'] = table.kernel_peak_c(legal)
            index = run.evaluate([legal])[0]
            fv = row['fv_peak_c'] = None if index is None else run.peaks[index]
        notes['results'].append(row)
        return legal, fv

    shortest = min(starts, key=lambda l: pin_manhattan_um(problem, l).sum())
    coolest, fv_low = confirm(None, solve(None))
    if coolest is not None and not calibrate:
        low, high = table.kernel_peak_c(coolest), table.kernel_peak_c(shortest)
        for cap in np.linspace(low, high, levels + 2)[1:-1]:
            confirm(cap, solve(cap))
    elif coolest is not None and fv_low is not None:
        index = run.evaluate([shortest])[0]
        if index is not None:
            bias = table.kernel_peak_c(coolest) - fv_low
            for target in np.linspace(fv_low, run.peaks[index], levels + 2)[1:-1]:
                cap = target + bias
                for _ in range(calibrate + 1):
                    _, fv = confirm(cap, solve(cap), target)
                    if fv is None:
                        break
                    cap += target - fv
    notes['cells'] = {str(o): len(c) for o, c in table.cells.items()}
    topology_slp(run, starts + candidates, rng, **kw)


METHODS = dict(random=random_search, pareto_ls=pareto_local_search, nsga=nsga_mutation,
               annealing=annealing, epsilon=epsilon_search, topology_lp=topology_lp, lp_epsilon=lp_then_epsilon,
               topology_slp=topology_slp, relation_space=relation_space,
               thermal_space=thermal_space)
