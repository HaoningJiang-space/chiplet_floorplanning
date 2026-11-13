"""Case1 crossover-only intervention; the frozen v1 search remains unchanged."""
from copy import deepcopy
import random
import time

from atplace_pin_geometry import placement_geometry
from atplace_search import CostLimit, Ledger, Space, dominates, profile, ranks_and_crowding

METHOD = 'nsga2_pin_guided_compatible'


def full_key(placement):
    return tuple((p['chiplet'], p['centre_x_um'], p['centre_y_um'], p['rotation_deg'])
                 for p in placement)


def compatible_crossover(space, a, b, rng, receipt):
    """Uniform over distinct legal mixed states, not over redundant parent masks."""
    if [p['chiplet'] for p in a] != [p['chiplet'] for p in b]:
        raise ValueError('Parent chiplet order differs')
    ka, kb = full_key(a), full_key(b)
    receipt.update(masks_checked=0, legal_masks=0, distinct_legal_states=0,
                   distinct_mixed_states=0, selection='incomplete')
    legal = {}
    for mask in range(1 << len(a)):
        if space.checks >= space.limit:
            raise CostLimit('candidate_check_cap')
        space.checks += 1
        receipt['masks_checked'] += 1
        p = [deepcopy(b[i] if mask & (1 << i) else a[i]) for i in range(len(a))]
        try:
            placement_geometry(space.source, p, space.gap)
        except ValueError:
            continue
        receipt['legal_masks'] += 1
        legal.setdefault(full_key(p), (mask, p))
    receipt['distinct_legal_states'] = len(legal)
    # A state differs from both parents iff it inherits a differing die from each.
    mixed = [item for key, item in legal.items() if key != ka and key != kb]
    receipt['distinct_mixed_states'] = len(mixed)
    if mixed:
        mask, p = rng.choice(mixed)
        selection = 'mixed'
    else:
        parents = [item for key, item in legal.items() if key in (ka, kb)]
        if not parents:
            raise ValueError('No legal parent in crossover enumeration')
        mask, p = rng.choice(parents)
        selection = 'parent_fallback'
    receipt.update(selection=selection, representative_mask=mask, placement=deepcopy(p))
    return deepcopy(p)


def run_policy(source, plan, solve):
    """Same NSGA-II loop as v1 B, with crossover replacement and extra receipts."""
    started = time.perf_counter()
    ledger = Ledger(source, plan, solve)
    initial = plan['initialization']
    space = Space(source, plan['gap_um'], plan['grid_um'], plan['candidate_check_cap'], initial['candidate_checks'])
    rng = random.Random(plan['seed']+1000000)
    status, reason, generations, offspring = 'complete_thermal_budget', None, 0, []
    population, generation_records = [], []
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
                return population[a if av < bv else b if bv < av else rng.choice((a, b))]
            offspring = []
            while len(offspring) < plan['population'] and len(ledger.thermal_records) < plan['thermal_budget']:
                event = ledger.begin('crossover_mutation')
                ar, br = tournament(), tournament()
                a, b = ar['placement'], br['placement']
                event['parent_rows'] = [ar['row_index'], br['row_index']]
                event['crossover'] = {}
                if rng.random() < .9:
                    p = compatible_crossover(space, a, b, rng, event['crossover'])
                else:
                    p = deepcopy(a)
                    event['crossover'].update(selection='bypassed', masks_checked=0, placement=deepcopy(p))
                for i in range(len(p)):
                    if rng.random() < 1/len(p):
                        p[i] = space.mutate(p, i, rng, True, ledger.score, plan['length_cap_m'])
                row = ledger.submit(p, event)
                if row is not None:
                    offspring.append(row)
            if len(offspring) == plan['population']:
                merged = population+offspring
                rank, crowd = ranks_and_crowding(merged)
                ties = {i: rng.random() for i in range(len(merged))}
                population = [merged[i] for i in sorted(range(len(merged)),
                    key=lambda i: (rank[i], -crowd[i], ties[i]))[:plan['population']]]
                generations += 1
                generation_records.append(dict(generation=generations,
                    population_rows=[r['row_index'] for r in population],
                    distinct_full_states=len({tuple(tuple(x) for x in r['layout_key']) for r in population}),
                    distinct_thermal_states=len({tuple(tuple(x) for x in r['thermal_key']) for r in population})))
    except CostLimit as error:
        status, reason = 'capped', str(error)
    except Exception as error:
        status, reason = 'failed_unknown', str(error)
    if ledger.events and ledger.events[-1]['status'] == 'generating':
        ledger.events[-1].update(status=status, reason=reason)
    crosses = [e['crossover'] for e in ledger.events if 'crossover' in e]
    result = dict(method=METHOD, seed=plan['seed'], status=status, reason=reason, rows=ledger.rows,
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
                              crossover_mask_checks=sum(c['masks_checked'] for c in crosses),
                              mixed_crossovers=sum(c['selection']=='mixed' for c in crosses),
                              parent_fallback_crossovers=sum(c['selection']=='parent_fallback' for c in crosses),
                              bypassed_crossovers=sum(c['selection']=='bypassed' for c in crosses),
                              prescreen_pin_seconds=ledger.pin_seconds, solve_seconds=ledger.solve_seconds,
                              elapsed_seconds=time.perf_counter()-started),
                  complete_generations=generations, final_generation_offspring=len(offspring),
                  generation_records=generation_records)
    result['physical_comparison'] = profile(ledger.rows, plan['length_cap_m'], plan['temperature_cap_c'])
    result['checkpoints'] = [dict(thermal_budget=q, **profile(
        [r for r in ledger.rows if r['thermal_queries_so_far'] <= q], plan['length_cap_m'], plan['temperature_cap_c']))
        for q in (16, 32, 48) if q <= len(ledger.thermal_records)]
    values = [(r['peak_c'], r['pin_length_m']) for r in ledger.rows]
    result['pareto_row_indices'] = [i for i, v in enumerate(values) if not any(dominates(w, v) for w in values)]
    return result
