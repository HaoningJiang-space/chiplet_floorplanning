"""Thermal lower bounds and feasible witnesses, without treating search as proof."""

import math


def summarize_decisions(rows):
    """Rows must cover the frozen finite placement/policy domain completely.

    No routing completeness is assumed. A witness at the global geometric
    thermal minimum closes the objective bound even when other routes are unknown.
    This is a proof about the supplied numerical model, not physical uncertainty.
    """
    ids = [row['id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate decision ID')
    geometry = [r for r in rows if r['geometry_feasible']]
    if any('thermal' not in r or not math.isfinite(r['thermal']['peak_c']) for r in geometry):
        raise ValueError('every legal placement needs a thermal lower-bound observation')
    # Duplicate route policies for a placement must share the same heat solution.
    temperatures = {}
    for row in geometry:
        key = row['layout_id']; t = row['thermal']['peak_c']
        if key in temperatures and abs(t-temperatures[key]) > 1e-9:
            raise ValueError('route-dependent temperatures invalidate fixed-power bound')
        temperatures[key] = t
    lower = min(temperatures.values(), default=None)
    stages = {'geometry': geometry,
              'routing': [r for r in geometry if r['routing_status']=='feasible']}
    for mode in ('reference', 'feedback'):
        electrical = [r for r in stages['routing'] if r.get('timing', {}).get(mode, {}).get('status')=='analyzed']
        stages['electrical_'+mode] = electrical
        stages['timing_'+mode] = [r for r in electrical if r['timing'][mode]['timing_feasible']]
    report = {}
    for name, values in stages.items():
        best = min(values, key=lambda r: (r['thermal']['peak_c'], r['id']), default=None)
        upper = best['thermal']['peak_c'] if best else None
        closed = lower is not None and upper is not None and abs(upper-lower) <= 1e-9
        report[name] = dict(evaluated_pairs=len(values), placement_count=len({r['layout_id'] for r in values}),
            lower_bound_c=lower, feasible_upper_bound_c=upper, best_witness=best['id'] if best else None,
            certified_numerical_optimum=closed, proof='thermal_lower_bound_attained' if closed else 'open_bound',
            empty_set_proven=(not geometry), physical_optimum_certified=False)
    costs = {}
    routing = report['routing']
    for mode in ('reference', 'feedback'):
        timing = report['timing_'+mode]
        r, t = routing['feasible_upper_bound_c'], timing['feasible_upper_bound_c']
        exact = routing['certified_numerical_optimum'] and timing['certified_numerical_optimum']
        costs[mode] = dict(evaluated_subset_penalty_k=t-r if t is not None and r is not None else None,
                          exact_penalty_k=t-r if exact else None,
                          penalty_bounds_k=[0., t-lower] if t is not None else None,
                          exact=exact)
    # Full-budget controls: identical evaluator calls; no speedup claim. Thermal
    # and timing ordering only changes traversal, not the common final objective.
    baseline = {}
    valid = stages['timing_feedback']
    for name in ('thermal_first', 'timing_first', 'sequential_filter'):
        if name=='thermal_first':
            ordered = sorted(geometry, key=lambda r: (r['thermal']['peak_c'], r['id']))
        elif name=='timing_first':
            ordered = sorted(geometry, key=lambda r: (
                -min(r.get('timing', {}).get('feedback', {}).get('worst_setup_ns', -math.inf),
                     r.get('timing', {}).get('feedback', {}).get('worst_hold_ns', -math.inf)), r['id']))
        else:
            ordered = sorted(geometry, key=lambda r: r['id'])
        ids_ok = {r['id'] for r in valid}
        feasible = [r for r in ordered if r['id'] in ids_ok]
        best = min(feasible, key=lambda r: (r['thermal']['peak_c'], r['id']), default=None)
        baseline[name] = dict(evaluator_calls=len(rows), feedback_feasible_pairs=len(feasible),
                             best_witness=best['id'] if best else None,
                             peak_c=best['thermal']['peak_c'] if best else None)
    return dict(stages=report, timing_temperature_cost=costs, baselines=baseline,
                baseline_scope='same_complete_evaluation_ledger_full_budget_control_no_efficiency_claim',
                routing_unknown_ids=[r['id'] for r in geometry if r['routing_status']=='search_failed'],
                reference_feasible_ids=[r['id'] for r in stages['timing_reference']],
                feedback_feasible_ids=[r['id'] for r in stages['timing_feedback']],
                proof_scope='finite_frozen_placement_domain_all_declared_fabric_routes_fixed_power_numerical_model',
                model_uncertainty_bound_available=False)
