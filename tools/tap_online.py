"""Same-domain online Pareto baselines; no SOTA or physical signoff claim."""
import copy
import math
import random
import time
from freeze_tap_geometry import candidates, separated, verify
from diagnose_tap_sensitivity import thermal_key
from build_tap_algorithm_oracle import centre_span


class LimitReached(Exception):
    pass


def objectives(row):
    return (round(row['peak_c']/1e-6), round(row['centre_span_mm']/1e-9))


def dominates(a, b):
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def ranks_and_crowding(rows):
    """Elitist NSGA-II rank and per-front normalized crowding distances."""
    remaining = set(range(len(rows)))
    values = [objectives(r) for r in rows]
    rank, crowd = {}, {}
    level = 0
    while remaining:
        front = sorted(i for i in remaining if not any(dominates(values[j], values[i]) for j in remaining))
        for i in front:
            rank[i], crowd[i] = level, 0.
        for axis in (0, 1):
            ordered = sorted(front, key=lambda i: (values[i][axis], i))
            width = values[ordered[-1]][axis]-values[ordered[0]][axis]
            if width == 0:
                continue
            crowd[ordered[0]] = crowd[ordered[-1]] = math.inf
            for k in range(1, len(ordered)-1):
                crowd[ordered[k]] += (values[ordered[k+1]][axis]-values[ordered[k-1]][axis])/width
        remaining.difference_update(front)
        level += 1
    return rank, crowd


def select_population(rows, count, rng):
    rank, crowd = ranks_and_crowding(rows)
    tie = {i: rng.random() for i in range(len(rows))}
    indices = sorted(range(len(rows)), key=lambda i: (rank[i], -crowd[i], tie[i]))[:count]
    return [rows[i] for i in indices]


def normalized(row, scale):
    return ((row['peak_c']-scale['temperature_origin_c'])/scale['temperature_scale_k'],
            (row['centre_span_mm']-scale['span_origin_mm'])/scale['span_scale_mm'])


def metrics(rows, scale):
    values = [objectives(r) for r in rows]
    archive = [i for i, v in enumerate(values) if not any(dominates(w, v) for w in values)]
    # Rectangle union to a frozen reference point. No clipping of good points.
    reference = scale['hypervolume_reference']
    points = sorted(set(normalized(rows[i], scale) for i in archive))
    height, volume = reference[1], 0.
    outside = 0
    for x, y in points:
        if x >= reference[0] or y >= reference[1]:
            outside += 1
            continue
        if y < height:
            volume += (reference[0]-x)*(height-y)
            height = y
    return dict(archive_query_indices=archive, hypervolume=volume,
                archive_points_outside_reference=outside,
                best_peak_c=min(r['peak_c'] for r in rows),
                best_centre_span_mm=min(r['centre_span_mm'] for r in rows))


class Space:
    def __init__(self, domain):
        self.domain = domain
        self.options = [list(candidates(domain, chip)) for chip in domain['chiplets']]
        self.construction_candidate_checks = 0

    def construct(self, rng):
        order = list(range(len(self.options)))
        rng.shuffle(order)
        placed, boxes = [], []
        for chip in order:
            legal = []
            for p, b in self.options[chip]:
                self.construction_candidate_checks += 1
                if all(separated(b, old, self.domain['minimum_gap_um']) for old in boxes):
                    legal.append((p, b))
            if not legal:
                return None
            p, b = rng.choice(legal)
            placed.append(copy.deepcopy(p))
            boxes.append(b)
        return sorted(placed, key=lambda p: p['id'])

    def mutate(self, placement, rng, operator=None):
        result = copy.deepcopy(placement)
        operator = operator or rng.choice(('move', 'rotate', 'swap', 'joint'))
        i = rng.randrange(len(result))
        if operator == 'swap':
            j = rng.choice([j for j in range(len(result)) if j != i])
            for key in ('centre_x_um', 'centre_y_um'):
                result[i][key], result[j][key] = result[j][key], result[i][key]
        elif operator == 'rotate':
            result[i]['rotation_deg'] = rng.choice([r for r in self.domain['rotations_deg'] if r != result[i]['rotation_deg']])
        elif operator in ('move', 'joint'):
            options = self.options[i]
            if operator == 'move':
                options = [(p, b) for p, b in options if p['rotation_deg'] == result[i]['rotation_deg']]
            result[i] = copy.deepcopy(rng.choice(options)[0])
        else:
            raise ValueError('Unknown operator')
        return result, operator


class Evaluator:
    """Private per-run cache. Solver failures stop and remain unknown."""
    def __init__(self, domain, solve, budget, scale, proposal_cap=10000):
        self.domain, self.solve, self.budget, self.scale = domain, solve, budget, scale
        self.proposal_cap = proposal_cap
        self.cache, self.rows, self.events, self.checkpoints = {}, [], [], []
        self.proposals = self.illegal = self.cache_hits = self.solve_attempts = 0
        self.geometry_seconds = self.solve_seconds = 0.
        self.started = time.perf_counter()

    def evaluate(self, placement, operator):
        if self.proposals >= self.proposal_cap:
            raise LimitReached('proposal_cap')
        self.proposals += 1
        event = dict(proposal=self.proposals, operator=operator, placement=placement)
        self.events.append(event)
        started = time.perf_counter()
        try:
            if placement is None:
                raise ValueError('incomplete sequential construction')
            verify(self.domain, placement)
        except ValueError as error:
            self.illegal += 1
            event.update(status='geometry_rejected', reason=str(error))
            return None
        finally:
            self.geometry_seconds += time.perf_counter()-started
        key = thermal_key(placement)
        if key in self.cache:
            self.cache_hits += 1
            event.update(status='cache_hit', query_index=self.cache[key]['query_index'])
            return self.cache[key]
        if self.solve_attempts >= self.budget:
            event['status'] = 'query_budget_exhausted'
            raise LimitReached('query_budget')
        self.solve_attempts += 1
        started = time.perf_counter()
        try:
            thermal = self.solve(placement)
            if not thermal['numerical_admission_passed'] or not math.isfinite(thermal['peak_power_layer_c']):
                raise ValueError('thermal numerical admission failed')
        except Exception as error:
            event.update(status='thermal_failed_unknown', reason=str(error))
            raise
        finally:
            self.solve_seconds += time.perf_counter()-started
        row = dict(query_index=len(self.rows), placement=copy.deepcopy(placement),
                   peak_c=thermal['peak_power_layer_c'], centre_span_mm=centre_span(self.domain, placement),
                   thermal=thermal)
        self.cache[key] = row
        self.rows.append(row)
        event.update(status='thermal_evaluated', query_index=row['query_index'])
        if len(self.rows) in (16, 32, 64):
            self.checkpoints.append(dict(queries=len(self.rows), proposals=self.proposals,
                                         elapsed_seconds=time.perf_counter()-self.started,
                                         **metrics(self.rows, self.scale)))
        return row


def run_policy(domain, initial, scale, method, seed, solve, budget=64, proposal_cap=10000):
    if method not in ('random', 'sa', 'nsga2') or budget < 16 or len(initial) != 16:
        raise ValueError('Invalid online protocol')
    if len({thermal_key(p) for p in initial}) != 16:
        raise ValueError('Initialization must contain 16 distinct thermal states')
    ev = Evaluator(domain, solve, budget, scale, proposal_cap)
    rng = random.Random(seed)
    status, reason = 'complete_query_budget', None
    generations = 0
    space = None
    try:
        space = Space(domain)
        population = [ev.evaluate(p, 'initial') for p in initial]
        if any(r is None for r in population):
            raise ValueError('Invalid frozen initialization')
        weights = (0., 1/3, 2/3, 1.)
        def scalar(row, weight):
            t, distance = normalized(row, scale)
            return weight*t+(1-weight)*distance
        chains = [min(population, key=lambda r: (scalar(r, w), r['query_index'])) for w in weights]
        chain_turn = 0
        while len(ev.rows) < budget:
            if method == 'random':
                ev.evaluate(space.construct(rng), 'random_construct')
            elif method == 'sa':
                k = chain_turn % 4
                chain_turn += 1
                placement, operator = space.mutate(chains[k]['placement'], rng)
                candidate = ev.evaluate(placement, operator)
                if candidate is None:
                    continue
                delta = scalar(candidate, weights[k])-scalar(chains[k], weights[k])
                progress = (len(ev.rows)-16)/max(1, budget-16)
                temperature = .1*(.01/.1)**progress
                if delta <= 0 or rng.random() < math.exp(-delta/temperature):
                    chains[k] = candidate
            else:
                rank, crowd = ranks_and_crowding(population)
                def tournament():
                    a, b = rng.sample(range(len(population)), 2)
                    va, vb = (rank[a], -crowd[a]), (rank[b], -crowd[b])
                    i = a if va < vb else b if vb < va else rng.choice((a, b))
                    return population[i]['placement']
                offspring = []
                target = min(16, budget-len(ev.rows))
                while len(offspring) < target:
                    a, b = tournament(), tournament()
                    if rng.random() < .9:
                        placement = [copy.deepcopy(rng.choice((x, y))) for x, y in zip(a, b)]
                    else:
                        placement = copy.deepcopy(a)
                    for i in range(len(placement)):
                        if rng.random() < 1/len(placement):
                            placement[i] = copy.deepcopy(rng.choice(space.options[i])[0])
                    old_count = len(ev.rows)
                    candidate = ev.evaluate(placement, 'crossover_mutation')
                    # Duplicate suppression is global within this run, explicitly charged as cache hits.
                    if len(ev.rows) > old_count:
                        offspring.append(candidate)
                population = select_population(population+offspring, 16, rng)
                generations += 1
    except LimitReached as error:
        status, reason = 'stopped_at_limit', str(error)
    except Exception as error:
        status, reason = 'failed_unknown', str(error)
    result = dict(status=status, reason=reason, method=method, seed=seed, budget=budget,
        queries=len(ev.rows), solve_attempts=ev.solve_attempts, proposals=ev.proposals,
        illegal_proposals=ev.illegal, cache_hits=ev.cache_hits,
        construction_candidate_checks=space.construction_candidate_checks if space else 0,
        geometry_seconds=ev.geometry_seconds, solve_seconds=ev.solve_seconds,
        elapsed_seconds=time.perf_counter()-ev.started, generations=generations,
        checkpoints=ev.checkpoints, rows=ev.rows, events=ev.events)
    if ev.rows:
        result['final_metrics'] = metrics(ev.rows, scale)
    return result
