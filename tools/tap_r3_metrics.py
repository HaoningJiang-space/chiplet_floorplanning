"""Physical layout comparisons at shared constraints; HV and effort are auxiliary."""
import math

from tap_online import metrics, objectives


def diagnostic_contract(rows):
    """Anchors from the earlier sensitivity sample, never from method results.

    Nearest-rank quartiles select observations, not interpolated layouts. These
    are research budgets, not product temperature limits or routing capacities.
    """
    spans = sorted(r['centre_span_mm'] for r in rows)
    temperatures = sorted(r['thermal']['peak_power_layer_c'] for r in rows)
    ranks = [(f'p{q}', math.ceil(len(rows)*q/100)-1) for q in (25, 50, 75)]
    return dict(schema='tap-physical-comparison-v1',
                interconnect_metric='demand_weighted_mean_centre_manhattan_mm',
                selection='raw inclusive <=; minimum objective, other objective, query index',
                anchor_rule='nearest-rank p25/p50/p75 of earlier sensitivity layouts',
                primary_anchor='p50',
                span_budgets=[dict(id=name, span_budget_mm=spans[i]) for name, i in ranks],
                temperature_caps=[dict(id=name, temperature_cap_c=temperatures[i]) for name, i in ranks])


def constrained_profile(rows, contract):
    """Select actual evaluated joint points. No interpolation or marginal pairing."""
    if contract['interconnect_metric'] != 'demand_weighted_mean_centre_manhattan_mm':
        raise ValueError('This evaluator measures centre span, not pin or routed length')
    def select(limit, constraint, objective, threshold):
        eligible = [r for r in rows if r[constraint] <= limit[threshold]]
        winner = min(eligible, key=lambda r: (r[objective], r[constraint], r['query_index'])) if eligible else None
        return dict(**limit, status='attained' if winner else 'not_attained',
                    eligible_layouts=len(eligible),
                    selected={k: winner[k] for k in ('query_index', 'peak_c', 'centre_span_mm')} if winner else None)
    return dict(contract=contract,
                temperature_at_span_budget=[select(b, 'centre_span_mm', 'peak_c', 'span_budget_mm')
                                            for b in contract['span_budgets']],
                span_at_temperature_cap=[select(b, 'peak_c', 'centre_span_mm', 'temperature_cap_c')
                                         for b in contract['temperature_caps']])


def paired_profiles(candidate, baseline):
    """Positive gains favor candidate; missing attainment is not zero improvement."""
    if candidate['contract'] != baseline['contract']:
        raise ValueError('Paired comparisons require identical physical constraints')
    def difference(a, b, axis):
        left, right = a['selected'], b['selected']
        status = ('both_attained' if left and right else 'candidate_only_attained' if left
                  else 'baseline_only_attained' if right else 'neither_attained')
        result = dict(id=a['id'], status=status, candidate=left, baseline=right)
        if axis == 'temperature':
            result.update(span_budget_mm=a['span_budget_mm'],
                          temperature_gain_k=right['peak_c']-left['peak_c'] if left and right else None)
        else:
            gain = right['centre_span_mm']-left['centre_span_mm'] if left and right else None
            result.update(temperature_cap_c=a['temperature_cap_c'], span_gain_mm=gain,
                          span_reduction_percent=100*gain/right['centre_span_mm']
                          if gain is not None and right['centre_span_mm'] > 0 else None)
        return result
    return dict(contract=candidate['contract'],
                temperature_at_span_budget=[difference(a, b, 'temperature') for a, b in zip(
                    candidate['temperature_at_span_budget'], baseline['temperature_at_span_budget'], strict=True)],
                span_at_temperature_cap=[difference(a, b, 'span') for a, b in zip(
                    candidate['span_at_temperature_cap'], baseline['span_at_temperature_cap'], strict=True)])


def summarize(result, scale, comparison=None):
    rows, events = result['rows'], result['events']
    physical = constrained_profile(rows, comparison) if comparison else None
    if len(rows) < 16:
        return dict(schema='tap-research-metrics-v2', status=result['status'], queries=len(rows),
                    physical_comparison=physical, auxiliary=None)
    initial = metrics(rows[:16], scale)
    final = metrics(rows, scale)
    legal = [e for e in events if e['status'] in ('thermal_evaluated', 'cache_hit')]
    unique = {tuple((p['id'], p['centre_x_um'], p['centre_y_um'], p['rotation_deg'])
                    for p in sorted(e['placement'], key=lambda p: p['id'])) for e in legal}
    proposals = result['proposals']
    search_events = [e for e in events if e['operator'] != 'initial']
    search_legal = sum(e['status'] in ('thermal_evaluated', 'cache_hit') for e in search_events)
    archive = [rows[i] for i in final['archive_query_indices']]
    checkpoints = sorted({16, len(rows)} | {c['queries'] for c in result['checkpoints']})
    return dict(schema='tap-research-metrics-v2', status=result['status'], queries=len(rows), budget=result['budget'],
                physical_comparison=physical,
                anytime_physical_comparison=[dict(queries=n, **constrained_profile(rows[:n], comparison))
                                             for n in checkpoints] if comparison else [],
                auxiliary=dict(hypervolume=final['hypervolume'],
                hypervolume_gain_from_initial=final['hypervolume']-initial['hypervolume'],
                anytime_hypervolume=[dict(queries=c['queries'], hypervolume=c['hypervolume'])
                                     for c in result['checkpoints']],
                marginal_best_peak_c=final['best_peak_c'],
                marginal_best_centre_span_mm=final['best_centre_span_mm'],
                marginal_temperature_gain_k=initial['best_peak_c']-final['best_peak_c'],
                marginal_span_gain_mm=initial['best_centre_span_mm']-final['best_centre_span_mm'],
                archive_objective_bins=len({objectives(r) for r in archive}),
                archive_points_outside_reference=final['archive_points_outside_reference']),
                effort=dict(unique_legal_full_layouts=len(unique), distinct_thermal_states=len(rows),
                unique_legal_layout_fraction=len(unique)/len(legal) if legal else 0.,
                legal_proposal_fraction=len(legal)/proposals if proposals else 0.,
                search_legal_proposal_fraction=search_legal/len(search_events) if search_events else None,
                illegal_proposal_fraction=result['illegal_proposals']/proposals if proposals else 0.,
                legal_cache_fraction=result['cache_hits']/len(legal) if legal else 0.,
                proposals=proposals, cache_hits=result['cache_hits'],
                elapsed_seconds=result['elapsed_seconds'], solve_seconds=result['solve_seconds'],
                geometry_seconds=result['geometry_seconds'],
                mutation_candidate_checks=result.get('mutation_candidate_checks', 0),
                mutation_filter_seconds=result.get('mutation_filter_seconds', 0.)))


def paired_difference(candidate, baseline):
    """One aligned case/seed; retain completion status and physical attainment."""
    if candidate['physical_comparison'] is None or baseline['physical_comparison'] is None:
        raise ValueError('Physical comparison contract required')
    return dict(physical_comparison=paired_profiles(candidate['physical_comparison'], baseline['physical_comparison']),
                auxiliary_hypervolume_difference=candidate['auxiliary']['hypervolume']-baseline['auxiliary']['hypervolume']
                if candidate['auxiliary'] and baseline['auxiliary'] else None,
                both_complete=candidate['status'] == baseline['status'] == 'complete_query_budget')
