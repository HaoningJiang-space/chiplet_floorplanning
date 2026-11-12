"""Compare three frozen layout-plus-routing pairs from independently replayed waves."""
import argparse
from itertools import combinations
import json
import math
from pathlib import Path

from chiplet_floorplanning.characterization import digest
from summarize_xyce_hot import summarize
from summarize_xyce_uniform import summarize as uniform_summary


def classify(cold, hot, controls_passed, uniform_discrepancy_ps):
    """Empirical resolution screen, never a physical confidence/error bound."""
    if len(cold) != 2 or len(hot) != 2 or not all(math.isfinite(x) for x in [*cold, *hot, uniform_discrepancy_ps]):
        raise ValueError('two finite time-step observations required')
    if uniform_discrepancy_ps < 0:
        raise ValueError('negative control discrepancy')
    def resolved_sign(values, control_terms=2):
        screen = max(abs(values[1]-values[0]), control_terms*uniform_discrepancy_ps)
        if min(values) > screen:
            return 1
        if max(values) < -screen:
            return -1
        return 0
    c, h = resolved_sign(cold), resolved_sign(hot)
    interaction = [h-c for c, h in zip(cold, hot)]
    return dict(cold_pair_difference_ps=cold, hot_pair_difference_ps=hot,
        interaction_ps=interaction,
        interaction_observed_range_ps=[min(interaction), max(interaction)],
        paired_step_sensitivity_ps=abs(interaction[1]-interaction[0]),
        ordering=('unresolved' if not controls_passed or not c or not h else
                  'stable' if c == h else 'changed'),
        interaction_status=('unresolved' if not controls_passed else
                            'observed_interaction' if resolved_sign(interaction, 4) else 'no_resolved_interaction'),
        physical_uncertainty='unquantified')


def compare(a, b, controls_passed, uniform_discrepancy_ps):
    expected = {(step, f'{g}_{lane}', edge, kind)
                for step in (5., 2.5) for g in range(2) for lane in range(4)
                for edge in ('rise', 'fall') for kind in ('setup', 'hold')}
    def index(report):
        if not report.get('complete') or not report.get('diagnostics_admitted'):
            raise ValueError('inadmissible layout summary')
        rows = {(r['step_ps'], r['lane'], r['edge'], r['window']): r for r in report['paths']}
        if len(rows) != len(report['paths']) or set(rows) != expected:
            raise ValueError('incomplete/duplicate path domain')
        return rows
    ia, ib = index(a), index(b)
    rows = []
    for lane, edge, kind in sorted({key[1:] for key in expected}):
        paired = [[(ib[step, lane, edge, kind][mode+'_window_ns']-
                    ia[step, lane, edge, kind][mode+'_window_ns'])*1000
                   for step in (5., 2.5)] for mode in ('cold', 'hot')]
        verdict = classify(*paired, controls_passed, uniform_discrepancy_ps)
        sta = {mode: (ib[2.5, lane, edge, kind]['sta_'+mode+'_window_ns']-
                      ia[2.5, lane, edge, kind]['sta_'+mode+'_window_ns'])*1000
               for mode in ('cold', 'hot')}
        rows.append(dict(lane=lane, edge=edge, window=kind, **verdict,
            sta_pair_difference_ps=sta,
            fine_model_order_agreement={mode: (paired[i][1]*sta[mode] > 0)
                                        for i, mode in enumerate(('cold', 'hot'))},
            interaction_model_difference_ps=verdict['interaction_ps'][1]-(sta['hot']-sta['cold'])))
    minima = []
    for kind in ('setup', 'hold'):
        critical, paired = {}, []
        sta_minima = {}
        for mode in ('cold', 'hot'):
            differences = []
            for step in (5., 2.5):
                best = [min((r for k, r in idx.items() if k[0] == step and k[3] == kind),
                            key=lambda r: r[mode+'_window_ns']) for idx in (ia, ib)]
                differences.append((best[1][mode+'_window_ns']-best[0][mode+'_window_ns'])*1000)
                critical[f'{mode}_{step:g}ps'] = [dict(lane=r['lane'], edge=r['edge'],
                    window_ns=r[mode+'_window_ns']) for r in best]
            paired.append(differences)
            sta_values = [min(r['sta_'+mode+'_window_ns'] for k, r in idx.items()
                              if k[0] == 2.5 and k[3] == kind) for idx in (ia, ib)]
            sta_minima[mode] = (sta_values[1]-sta_values[0])*1000
        minima.append(dict(window=kind, **classify(*paired, controls_passed, uniform_discrepancy_ps),
                           sta_pair_difference_ps=sta_minima,
                           interaction_model_difference_ps=(paired[1][1]-paired[0][1])-
                               (sta_minima['hot']-sta_minima['cold']),
                           critical_paths_a_b=critical))
    return dict(paths=rows, minimum_windows=minima)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    layouts = manifest['layouts']
    if set(layouts) != {'rot180', 'rot90', 'rot270'}:
        raise ValueError('exact frozen three-layout domain required')
    uniform = manifest['uniform']
    controls = [uniform_summary(Path(root), Path(uniform['cold']), Path(uniform['layout']))
                for root in uniform['runs']]
    if sorted(r['temperature_c'] for r in controls) != [25, 65]:
        raise ValueError('missing uniform-control temperature')
    passed = all(r['numerical_control_passed'] for r in controls)
    discrepancy = max(r['max_abs_difference_ps'] for r in controls)
    summaries = {name: summarize(Path(x['hot']), Path(x['cold']), Path(x['layout']))
                 for name, x in layouts.items()}
    if len({r['cold_receipt_sha256'] for r in summaries.values()}) != 3:
        raise ValueError('duplicate layout evidence')
    pairs = {a+'__'+b: compare(summaries[a], summaries[b], passed, discrepancy)
             for a, b in combinations(('rot180', 'rot90', 'rot270'), 2)}
    result = dict(execution_complete=True, physical_qualified=False,
        source_sha256=digest(__file__), manifest_sha256=digest(args.manifest),
        scope='three fixed layouts and routes; available windows, not slack or global optimum',
        numerical_screen='same sign at both steps and magnitude greater than max(step variation, control terms times observed uniform discrepancy); 2 terms for pair differences, 4 for interaction; empirical only',
        step_order_ps=[5., 2.5], uniform_controls=controls, summaries=summaries, pairs=pairs)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({name: {kind: sum(r['ordering'] == kind for r in pair['paths'])
                             for kind in ('stable', 'changed', 'unresolved')} for name, pair in pairs.items()}, indent=2))


if __name__ == '__main__':
    main()
