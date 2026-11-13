"""One-case NSGA-II screening ablation with separate layout and thermal ledgers."""
from copy import deepcopy
import math
import random
import time

from atplace_pin_geometry import UniformDiePinEvaluator, pin_objective, placement_geometry


class CostLimit(Exception):
    pass


def identities(source, placement, gap_um):
    poses, bounds = placement_geometry(source, placement, gap_um)
    full = tuple((name, p['centre_x_um'], p['centre_y_um'], p['rotation_deg'])
                 for name, p in sorted(poses.items()))
    thermal = tuple((name, *(str(v) for v in box)) for name, box in sorted(bounds.items()))
    return full, thermal


def separated(a, b, gap):
    return a[2]+gap <= b[0] or b[2]+gap <= a[0] or a[3]+gap <= b[1] or b[3]+gap <= a[1]


class Space:
    def __init__(self, source, gap_um, grid_um, check_limit, initial_checks=0):
        self.source, self.gap, self.grid = source, gap_um, grid_um
        self.limit, self.checks = check_limit, initial_checks
        self.empty_mutation_sets = self.illegal_context_fallbacks = 0
        self.chips = {c['name']: c for c in source['chiplets']}
        self.options = {}
        for name in self.chips:
            options = []
            for angle in (0, 90, 180, 270):
                w, h = self.dimensions(name, angle)
                for x in range(math.ceil(w/2/grid_um)*grid_um,
                               math.floor((source['interposer_width_um']-w/2)/grid_um)*grid_um+1, grid_um):
                    for y in range(math.ceil(h/2/grid_um)*grid_um,
                                   math.floor((source['interposer_height_um']-h/2)/grid_um)*grid_um+1, grid_um):
                        p = dict(chiplet=name, centre_x_um=x, centre_y_um=y, rotation_deg=angle)
                        options.append((p, self.box(p)))
            self.options[name] = options

    def dimensions(self, name, angle):
        c = self.chips[name]
        w, h = c['width_um'], c['height_um']
        return (h, w) if angle % 180 else (w, h)

    def box(self, p):
        w, h = self.dimensions(p['chiplet'], p['rotation_deg'])
        x, y = p['centre_x_um'], p['centre_y_um']
        return x-w/2, y-h/2, x+w/2, y+h/2

    def legal_options(self, name, others):
        legal = []
        for p, box in self.options[name]:
            if self.checks >= self.limit:
                raise CostLimit('candidate_check_cap')
            self.checks += 1
            if all(separated(box, b, self.gap) for b in others):
                legal.append(p)
        return legal

    def construct(self, rng):
        order = list(self.chips)
        rng.shuffle(order)
        order.sort(key=lambda name: -self.chips[name]['width_um']*self.chips[name]['height_um'])
        placement, boxes = [], []
        for name in order:
            choices = self.legal_options(name, boxes)
            if not choices:
                return None
            p = deepcopy(rng.choice(choices))
            placement.append(p)
            boxes.append(self.box(p))
        return sorted(placement, key=lambda p: list(self.chips).index(p['chiplet']))

    def mutate(self, placement, index, rng, guided, score, length_cap_m):
        others = [self.box(p) for j, p in enumerate(placement) if j != index]
        choices = self.legal_options(placement[index]['chiplet'], others)
        if not choices:
            self.empty_mutation_sets += 1
            return deepcopy(placement[index])
        if not guided:
            return deepcopy(rng.choice(choices))
        # A single-chip mutation cannot cure overlap between two other chips.
        # Both methods use the same uniform fallback until later mutations repair it.
        if any(not separated(a, b, self.gap) for i, a in enumerate(others) for b in others[i+1:]):
            self.illegal_context_fallbacks += 1
            return deepcopy(rng.choice(choices))
        pool = rng.sample(choices, min(4, len(choices)))
        values = []
        for p in pool:
            candidate = deepcopy(placement)
            candidate[index] = deepcopy(p)
            values.append(score(candidate)['total_pin_manhattan_m'])
        eligible = [i for i, value in enumerate(values) if value <= length_cap_m]
        if not eligible:
            eligible = [i for i, value in enumerate(values) if value == min(values)]
        return deepcopy(pool[rng.choice(eligible)])


def initialize(source, base, plan):
    started = time.perf_counter()
    space = Space(source, plan['gap_um'], plan['grid_um'], plan['candidate_check_cap'])
    rng = random.Random(plan['seed'])
    initial, seen = [deepcopy(base)], {identities(source, base, plan['gap_um'])[1]}
    attempts = 0
    while len(initial) < plan['population'] and attempts < plan['proposal_cap']-1:
        attempts += 1
        p = space.construct(rng)
        if p is None:
            continue
        key = identities(source, p, plan['gap_um'])[1]
        if key not in seen:
            initial.append(p)
            seen.add(key)
    if len(initial) != plan['population']:
        raise ValueError('Initialization exhausted; unknown, not global infeasibility')
    return dict(placements=initial, construction_attempts=attempts,
                candidate_checks=space.checks, elapsed_seconds=time.perf_counter()-started,
                distribution='base plus descending-area sequential legal construction; seeded random ties; not uniform over joint layouts')


def objective(row):
    return round(row['peak_c']/1e-6), round(row['pin_length_m']/1e-9)


def dominates(a, b):
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def ranks_and_crowding(rows):
    values = [objective(r) for r in rows]
    remaining, rank, crowd, level = set(range(len(rows))), {}, {}, 0
    while remaining:
        front = sorted(i for i in remaining if not any(dominates(values[j], values[i]) for j in remaining))
        for i in front:
            rank[i], crowd[i] = level, 0.
        for axis in (0, 1):
            ordered = sorted(front, key=lambda i: (values[i][axis], i))
            width = values[ordered[-1]][axis]-values[ordered[0]][axis]
            if not width:
                continue
            crowd[ordered[0]] = crowd[ordered[-1]] = math.inf
            for k in range(1, len(ordered)-1):
                crowd[ordered[k]] += (values[ordered[k+1]][axis]-values[ordered[k-1]][axis])/width
        remaining.difference_update(front)
        level += 1
    return rank, crowd


def profile(rows, length_cap_m, temperature_cap_c):
    def pick(constraint, cap, target):
        eligible = [r for r in rows if r[constraint] <= cap]
        winner = min(eligible, key=lambda r: (r[target], r[constraint], r['row_index'])) if eligible else None
        return dict(status='attained' if winner else 'not_attained', eligible_layouts=len(eligible),
                    selected=deepcopy(winner) if winner else None)
    return dict(length_cap_m=length_cap_m, temperature_cap_c=temperature_cap_c,
                temperature_at_length=pick('pin_length_m', length_cap_m, 'peak_c'),
                length_at_temperature=pick('peak_c', temperature_cap_c, 'pin_length_m'))


class Ledger:
    def __init__(self, source, plan, solve):
        self.source, self.plan, self.solve = source, plan, solve
        self.rows, self.events, self.thermal_records, self.seen = [], [], [], {}
        init = plan.get('initialization', {})
        self.initial_retry_proposals = max(0, init.get('construction_attempts', 0)+1-len(init.get('placements', [None])))
        self.pin_calls = self.solve_attempts = self.duplicate_proposals = self.illegal_proposals = 0
        self.prescreen_pin_calls = 0
        self.pin_seconds = self.solve_seconds = 0.
        self.evaluator = UniformDiePinEvaluator(source, plan['gap_um'], self.solve_thermal)

    def solve_thermal(self, data):
        if len(self.thermal_records) >= self.plan['thermal_budget']:
            raise CostLimit('thermal_budget')
        self.solve_attempts += 1
        started = time.perf_counter()
        try:
            thermal = self.solve(data)
        finally:
            self.solve_seconds += time.perf_counter()-started
        if not thermal['numerical_admission_passed']:
            raise ValueError('Thermal numerical admission failed')
        row = dict(solve_id=len(self.thermal_records), thermal=thermal)
        self.thermal_records.append(row)
        return row

    def pin_call(self):
        if self.pin_calls >= self.plan['pin_call_cap']:
            raise CostLimit('pin_call_cap')
        self.pin_calls += 1

    def score(self, placement):
        self.pin_call()
        self.prescreen_pin_calls += 1
        started = time.perf_counter()
        try:
            return pin_objective(self.source, placement, self.plan['gap_um'])
        finally:
            self.pin_seconds += time.perf_counter()-started

    def begin(self, operator):
        if len(self.events)+self.initial_retry_proposals >= self.plan['proposal_cap']:
            raise CostLimit('proposal_cap')
        event = dict(proposal=len(self.events)+self.initial_retry_proposals+1,
                     operator=operator, status='generating', placement=None)
        self.events.append(event)
        return event

    def submit(self, placement, event):
        event['placement'] = deepcopy(placement)
        try:
            if any(type(p[k]) is not int or p[k] % self.plan['grid_um']
                   for p in placement for k in ('centre_x_um', 'centre_y_um')):
                raise ValueError('Search placement is off the frozen centre grid')
            full, thermal_key = identities(self.source, placement, self.plan['gap_um'])
        except ValueError:
            event['status'] = 'illegal'
            self.illegal_proposals += 1
            return None
        if full in self.seen:
            event.update(status='duplicate_full_state', row_index=self.seen[full])
            self.duplicate_proposals += 1
            return None
        self.pin_call()  # UniformDiePinEvaluator recomputes exactly one full pin objective.
        evaluated = self.evaluator.evaluate(placement)
        solved, metric = evaluated['thermal_result'], evaluated['metric']
        row = dict(row_index=len(self.rows), proposal=event['proposal'], placement=deepcopy(placement),
                   layout_key=[list(x) for x in full], thermal_key=[list(x) for x in thermal_key],
                   thermal_solve_id=solved['solve_id'], thermal_cache_hit=evaluated['thermal_cache_hit'],
                   thermal_queries_so_far=len(self.thermal_records),
                   peak_c=solved['thermal']['peak_power_layer_c'], pin_length_m=metric['total_pin_manhattan_m'],
                   pin_length_um_decimal=metric['total_pin_manhattan_um_decimal'])
        self.rows.append(row)
        self.seen[full] = row['row_index']
        event.update(status='cache_hit_new_layout' if row['thermal_cache_hit'] else 'thermal_evaluated',
                     row_index=row['row_index'])
        return row


def run_policy(source, plan, method, solve):
    if method not in ('nsga2_legal', 'nsga2_pin_guided'):
        raise ValueError('Unknown method')
    started = time.perf_counter()
    ledger = Ledger(source, plan, solve)
    initial = plan['initialization']
    space = Space(source, plan['gap_um'], plan['grid_um'], plan['candidate_check_cap'], initial['candidate_checks'])
    rng = random.Random(plan['seed']+1000000)
    status, reason, generations, offspring = 'complete_thermal_budget', None, 0, []
    try:
        population = [ledger.submit(p, ledger.begin('initial')) for p in initial['placements']]
        if any(r is None or r['thermal_cache_hit'] for r in population):
            raise ValueError('Initialization must contain distinct legal thermal states')
        base = population[0]
        if base['peak_c'] != plan['temperature_cap_c'] or base['pin_length_m'] != plan['length_cap_m']:
            raise ValueError('Base anchor reproduction mismatch; do not loosen thresholds')
        while len(ledger.thermal_records) < plan['thermal_budget']:
            rank, crowd = ranks_and_crowding(population)
            def tournament():
                a, b = rng.sample(range(len(population)), 2)
                av, bv = (rank[a], -crowd[a]), (rank[b], -crowd[b])
                return population[a if av < bv else b if bv < av else rng.choice((a, b))]['placement']
            offspring = []
            while len(offspring) < plan['population'] and len(ledger.thermal_records) < plan['thermal_budget']:
                event = ledger.begin('crossover_mutation')
                a, b = tournament(), tournament()
                p = ([deepcopy(rng.choice((x, y))) for x, y in zip(a, b)]
                     if rng.random() < .9 else deepcopy(a))
                for i in range(len(p)):
                    if rng.random() < 1/len(p):
                        p[i] = space.mutate(p, i, rng, method == 'nsga2_pin_guided', ledger.score, plan['length_cap_m'])
                row = ledger.submit(p, event)
                if row is not None:
                    offspring.append(row)  # Includes new full orientations reusing a thermal solve.
            if len(offspring) == plan['population']:
                merged = population+offspring
                rank, crowd = ranks_and_crowding(merged)
                ties = {i: rng.random() for i in range(len(merged))}
                population = [merged[i] for i in sorted(range(len(merged)),
                    key=lambda i: (rank[i], -crowd[i], ties[i]))[:plan['population']]]
                generations += 1
    except CostLimit as error:
        status, reason = 'capped', str(error)
    except Exception as error:
        status, reason = 'failed_unknown', str(error)
    if ledger.events and ledger.events[-1]['status'] == 'generating':
        ledger.events[-1].update(status=status, reason=reason)
    result = dict(method=method, seed=plan['seed'], status=status, reason=reason, rows=ledger.rows,
                  events=ledger.events, thermal_records=ledger.thermal_records,
                  effort=dict(proposals=len(ledger.events)+ledger.initial_retry_proposals, pin_calls=ledger.pin_calls,
                              initial_retry_proposals=ledger.initial_retry_proposals,
                              prescreen_pin_calls=ledger.prescreen_pin_calls,
                              thermal_queries=len(ledger.thermal_records), solve_attempts=ledger.solve_attempts,
                              thermal_cache_hits=ledger.evaluator.cache_hits,
                              unique_full_layouts=len(ledger.rows), duplicate_full_proposals=ledger.duplicate_proposals,
                              illegal_proposals=ledger.illegal_proposals, candidate_checks=space.checks,
                              initial_candidate_checks=initial['candidate_checks'],
                              initial_construction_attempts=initial['construction_attempts'],
                              shared_initialization_seconds=initial['elapsed_seconds'],
                              empty_mutation_sets=space.empty_mutation_sets,
                              illegal_context_fallbacks=space.illegal_context_fallbacks,
                              prescreen_pin_seconds=ledger.pin_seconds, solve_seconds=ledger.solve_seconds,
                              elapsed_seconds=time.perf_counter()-started),
                  complete_generations=generations, final_generation_offspring=len(offspring))
    result['physical_comparison'] = profile(ledger.rows, plan['length_cap_m'], plan['temperature_cap_c'])
    result['checkpoints'] = [dict(thermal_budget=q, **profile(
        [r for r in ledger.rows if r['thermal_queries_so_far'] <= q], plan['length_cap_m'], plan['temperature_cap_c']))
        for q in (16, 32, 48) if q <= len(ledger.thermal_records)]
    values = [(r['peak_c'], r['pin_length_m']) for r in ledger.rows]
    result['pareto_row_indices'] = [i for i, v in enumerate(values) if not any(dominates(w, v) for w in values)]
    return result
