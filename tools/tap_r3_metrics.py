"""Common quality, diversity and effort metrics for an R3 trial ledger."""
from tap_online import metrics, objectives


def summarize(result, scale):
    rows, events = result['rows'], result['events']
    if len(rows) < 16:
        return dict(status=result['status'], queries=len(rows), quality_metrics=None)
    initial = metrics(rows[:16], scale)
    final = metrics(rows, scale)
    legal = [e for e in events if e['status'] in ('thermal_evaluated', 'cache_hit')]
    unique = {tuple((p['id'], p['centre_x_um'], p['centre_y_um'], p['rotation_deg'])
                    for p in sorted(e['placement'], key=lambda p: p['id'])) for e in legal}
    proposals = result['proposals']
    search_events = [e for e in events if e['operator'] != 'initial']
    search_legal = sum(e['status'] in ('thermal_evaluated', 'cache_hit') for e in search_events)
    archive = [rows[i] for i in final['archive_query_indices']]
    return dict(status=result['status'], queries=len(rows), budget=result['budget'],
                hypervolume=final['hypervolume'],
                hypervolume_gain_from_initial=final['hypervolume']-initial['hypervolume'],
                anytime_hypervolume=[dict(queries=c['queries'], hypervolume=c['hypervolume'])
                                     for c in result['checkpoints']],
                best_peak_c=final['best_peak_c'],
                best_centre_span_mm=final['best_centre_span_mm'],
                marginal_temperature_gain_k=initial['best_peak_c']-final['best_peak_c'],
                marginal_span_gain_mm=initial['best_centre_span_mm']-final['best_centre_span_mm'],
                archive_objective_bins=len({objectives(r) for r in archive}),
                archive_points_outside_reference=final['archive_points_outside_reference'],
                unique_legal_full_layouts=len(unique), distinct_thermal_states=len(rows),
                unique_legal_layout_fraction=len(unique)/len(legal) if legal else 0.,
                legal_proposal_fraction=len(legal)/proposals if proposals else 0.,
                search_legal_proposal_fraction=search_legal/len(search_events) if search_events else None,
                illegal_proposal_fraction=result['illegal_proposals']/proposals if proposals else 0.,
                legal_cache_fraction=result['cache_hits']/len(legal) if legal else 0.,
                proposals=proposals, cache_hits=result['cache_hits'],
                elapsed_seconds=result['elapsed_seconds'], solve_seconds=result['solve_seconds'],
                geometry_seconds=result['geometry_seconds'],
                mutation_candidate_checks=result.get('mutation_candidate_checks', 0),
                mutation_filter_seconds=result.get('mutation_filter_seconds', 0.))


def paired_difference(candidate, baseline):
    """Quality differences for one case/seed; positive gains favor candidate."""
    return dict(hypervolume=candidate['hypervolume']-baseline['hypervolume'],
                temperature_gain_k=baseline['best_peak_c']-candidate['best_peak_c'],
                span_gain_mm=baseline['best_centre_span_mm']-candidate['best_centre_span_mm'],
                elapsed_change_seconds=candidate['elapsed_seconds']-baseline['elapsed_seconds'],
                both_complete=candidate['status'] == baseline['status'] == 'complete_query_budget')
