"""Align selection with min peak temperature subject to the frozen pin budget."""
from copy import deepcopy
import random
import time

from atplace_slack_guided import guided_slack_crossover
from atplace_search import CostLimit, Ledger, Space, dominates, profile

METHOD = 'ga_length_constrained_slack_pool'


def selection_key(row, length_cap_m):
    """Lexicographic constrained objective; never add temperatures and distances."""
    length, temperature = row['pin_length_m'], row['peak_c']
    if length <= length_cap_m:
        return 0, temperature, length
    return 1, length-length_cap_m, temperature


def run_policy(source, plan, solve):
    """E operators and budgets; feasibility-first temperature selection replaces Pareto ranks."""
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
            priorities = [selection_key(r, plan['length_cap_m']) for r in population]
            def tournament():
                a, b = rng.sample(range(len(population)), 2)
                av, bv = priorities[a], priorities[b]
                return population[a if av < bv else b if bv < av else rng.choice((a, b))]
            offspring = []
            while len(offspring) < plan['population'] and len(ledger.thermal_records) < plan['thermal_budget']:
                event = ledger.begin('crossover_mutation')
                ar, br = tournament(), tournament()
                a, b = ar['placement'], br['placement']
                event['parent_rows'] = [ar['row_index'], br['row_index']]
                event['parent_selection_keys'] = [list(selection_key(r, plan['length_cap_m'])) for r in (ar, br)]
                event['crossover'] = {}
                if rng.random() < .9:
                    p = guided_slack_crossover(space, a, b, rng, event['crossover'], ledger.score, plan['length_cap_m'])
                else:
                    p = deepcopy(a)
                    event['crossover'].update(selection='bypassed', geometry_checks=0, topology_pair_checks=0, pin_calls=0, placement=deepcopy(p))
                for i in range(len(p)):
                    if rng.random() < 1/len(p):
                        p[i] = space.mutate(p, i, rng, True, ledger.score, plan['length_cap_m'])
                row = ledger.submit(p, event)
                if row is not None:
                    offspring.append(row)
            if len(offspring) == plan['population']:
                merged = population+offspring
                priorities = [selection_key(r, plan['length_cap_m']) for r in merged]
                ties = {i: rng.random() for i in range(len(merged))}
                population = [merged[i] for i in sorted(range(len(merged)),
                    key=lambda i: (*priorities[i], ties[i]))[:plan['population']]]
                generations += 1
                generation_records.append(dict(generation=generations,
                    population_rows=[r['row_index'] for r in population],
                    distance_feasible_count=sum(r['pin_length_m'] <= plan['length_cap_m'] for r in population),
                    selection_keys=[list(selection_key(r, plan['length_cap_m'])) for r in population],
                    distinct_full_states=len({tuple(tuple(x) for x in r['layout_key']) for r in population}),
                    distinct_thermal_states=len({tuple(tuple(x) for x in r['thermal_key']) for r in population})))
    except CostLimit as error:
        status, reason = 'capped', str(error)
    except Exception as error:
        status, reason = 'failed_unknown', str(error)
    if ledger.events and ledger.events[-1]['status'] == 'generating':
        ledger.events[-1].update(status=status, reason=reason)
    crosses = [e['crossover'] for e in ledger.events if 'crossover' in e]
    result = dict(method=METHOD, selection_rule='length_feasible_then_temperature', seed=plan['seed'], status=status, reason=reason, rows=ledger.rows,
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
                              crossover_geometry_checks=sum(c['geometry_checks'] for c in crosses),
                              topology_pair_checks=sum(c['topology_pair_checks'] for c in crosses),
                              crossover_pin_calls=sum(c['pin_calls'] for c in crosses),
                              crossover_candidates=sum(len(c.get('candidates', [])) for c in crosses),
                              pools_with_feasible_candidate=sum(c.get('feasible_candidates', 0) > 0 for c in crosses),
                              novel_reconstructions=sum(c['selection']=='novel_reconstruction' for c in crosses),
                              parent_reconstructions=sum(c['selection']=='parent_reconstruction' for c in crosses),
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
