"""TAP-derived coordinate proposals, isolated from the frozen online pilot.

This is an adapter component, not a complete published-method reproduction.
Every attempted geometry goes through the common evaluator and proposal cap.
"""
import copy
import math
import random
import time


class NeighbourhoodExhausted(Exception):
    """No legal one-step neighbour; says nothing about global feasibility."""


def close_move(evaluator, placement, rng):
    order = list(range(len(placement)))
    rng.shuffle(order)
    grid = evaluator.domain['centre_grid_um']
    for index in order:
        directions = [(0, -grid), (0, grid), (-grid, 0), (grid, 0)]
        rng.shuffle(directions)
        for dx, dy in directions:
            candidate = copy.deepcopy(placement)
            candidate[index]['centre_x_um'] += dx
            candidate[index]['centre_y_um'] += dy
            row = evaluator.evaluate(candidate, 'tap_close')
            if row is not None:
                return row
    raise NeighbourhoodExhausted('all one-grid-step moves rejected; global feasibility unknown')


def propose(evaluator, placement, rng, mode=None, jump_attempts=10001):
    """First legal close/jump candidate, with all rejected attempts charged.

    Uses one injected Python RNG instead of upstream's mixed NumPy/Python RNGs.
    A jump optionally rotates the *current* orientation by 90 degrees. Exhausted
    jumps fall back to close moves with the same row return type. Budget and
    numerical failures propagate unchanged, never masquerading as no neighbour.
    """
    if mode not in (None, 'close', 'jump'):
        raise ValueError('unknown move mode')
    if type(jump_attempts) is not int or jump_attempts < 1:
        raise ValueError('positive integer retry limit required')
    domain = evaluator.domain
    grid, side = domain['centre_grid_um'], domain['interposer_side_um']
    if side % grid or side // grid < 2 or set(domain['rotations_deg']) != {0, 90, 180, 270}:
        raise ValueError('adapter requires divisible centre grid and four rotations')
    mode = mode or ('jump' if rng.random() < 0.1 else 'close')
    if mode == 'jump':
        for _ in range(jump_attempts):
            candidate = copy.deepcopy(placement)
            index = rng.randrange(len(candidate))
            candidate[index]['centre_x_um'] = rng.randrange(1, side // grid) * grid
            candidate[index]['centre_y_um'] = rng.randrange(1, side // grid) * grid
            candidate[index]['rotation_deg'] = (candidate[index]['rotation_deg'] + 90*rng.randrange(2)) % 360
            row = evaluator.evaluate(candidate, 'tap_jump')
            if row is not None:
                return row
    return close_move(evaluator, placement, rng)


def acceptance(old, new, observed, temperature):
    """Upstream default adpTWv2, with ranges updated before acceptance.

    observed is ((min_temperature, max_temperature), (min_span, max_span)).
    The original length_max origin cancels in the difference. When either range
    vanishes, upstream uses raw differences for BOTH axes; preserve that branch.
    """
    peak = max(old['peak_c'], new['peak_c'])
    a = 0. if peak < 80 else min(.1+(peak-45)*.01, .9)
    b = 1-a
    dt = new['peak_c']-old['peak_c']
    dl = new['centre_span_mm']-old['centre_span_mm']
    tr, lr = (high-low for low, high in observed)
    delta = a*dt/tr+b*dl/lr if tr != 0 and lr != 0 else a*dt+b*dl
    return 1. if delta <= 0 else math.exp(-delta/temperature)


def run_tap_policy(domain, initial, scale, seed, solve, budget=64, proposal_cap=10000, comparison=None):
    """Single-chain source-derived TAP policy with a query-budget schedule."""
    from tap_online import Evaluator, LimitReached, metrics
    from diagnose_tap_sensitivity import thermal_key
    if budget < 16 or len(initial) != 16 or len({thermal_key(p) for p in initial}) != 16:
        raise ValueError('Expected 16 distinct shared initial states')
    ev = Evaluator(domain, solve, budget, scale, proposal_cap)
    rng = random.Random(seed+1000000)
    status, reason = 'complete_query_budget', None
    decisions = []
    observed = [[math.inf, -math.inf], [math.inf, -math.inf]]
    def update(row):
        for limits, value in zip(observed, (row['peak_c'], row['centre_span_mm'])):
            limits[0], limits[1] = min(limits[0], value), max(limits[1], value)
    try:
        population = [ev.evaluate(p, 'initial') for p in initial]
        if any(r is None for r in population):
            raise ValueError('Invalid shared initialization')
        for row in population:
            update(row)
        current = population[0]  # Shared first-fit; no objective-selected start.
        while len(ev.rows) < budget:
            before = len(ev.rows)
            temperature = .01**((before-16)/max(1, budget-17))
            candidate = propose(ev, current['placement'], rng)
            update(candidate)
            probability = acceptance(current, candidate, observed, temperature)
            draw = rng.random()
            accepted = draw < probability
            decisions.append(dict(proposal=ev.proposals, old_query_index=current['query_index'],
                                  candidate_query_index=candidate['query_index'],
                                  temperature=temperature, observed=copy.deepcopy(observed),
                                  probability=probability, draw=draw, accepted=accepted))
            if accepted:
                current = candidate
    except (LimitReached, NeighbourhoodExhausted) as error:
        status, reason = 'stopped_at_limit', str(error)
    except Exception as error:
        status, reason = 'failed_unknown', str(error)
    result = dict(status=status, reason=reason, method='tap_sa', seed=seed,
                  search_seed=seed+1000000, budget=budget, queries=len(ev.rows),
                  solve_attempts=ev.solve_attempts, proposals=ev.proposals,
                  illegal_proposals=ev.illegal, cache_hits=ev.cache_hits,
                  construction_candidate_checks=0, geometry_seconds=ev.geometry_seconds,
                  solve_seconds=ev.solve_seconds, elapsed_seconds=time.perf_counter()-ev.started,
                  generations=0, checkpoints=ev.checkpoints, rows=ev.rows, events=ev.events,
                  decisions=decisions)
    if ev.rows:
        result['final_metrics'] = metrics(ev.rows, scale)
    from tap_r3_metrics import summarize
    result['research_metrics'] = summarize(result, scale, comparison)
    return result
