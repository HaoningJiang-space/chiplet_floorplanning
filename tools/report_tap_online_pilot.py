"""Paired descriptive analysis and scientific figures for a COMPLETE pilot only."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from build_tap_ihp_endpoints import source_bytes

CASES = ('ascend910', 'micro150', 'multigpu')
METHODS = ('random', 'sa', 'nsga2')
SEEDS = tuple(range(2026111200, 2026111205))


def distribution(values):
    return dict(values=values, minimum=min(values), median=statistics.median(values), maximum=max(values))


def pooled_front(records):
    bins = {}
    for r in records:
        for p in r['points']:
            b = (round(p['peak_c']/1e-6), round(p['centre_span_mm']/1e-9))
            bins.setdefault(b, []).append(dict(method=r['method'], seed=r['seed'],
                query_index=p['query_index'], peak_c=p['peak_c'], centre_span_mm=p['centre_span_mm']))
    result, lowest_span = [], math.inf
    for (temperature, span), members in sorted(bins.items()):
        if span < lowest_span:
            result.append(dict(temperature_bin=temperature, span_bin=span, members=members))
            lowest_span = span
    return result


def analyze(data):
    if data['status'] != 'complete_pilot_verified' or data['verified_runs'] != 45 or not data['policy_replay']:
        raise ValueError('Complete verified/replayed 45-run evidence required')
    records = data['records']
    indexed = {(r['case'], r['method'], r['seed']): r for r in records}
    expected = {(c, m, s) for c in CASES for m in METHODS for s in SEEDS}
    if len(records) != 45 or set(indexed) != expected:
        raise ValueError('Missing, duplicate or unexpected paired trials')
    summaries, paired = [], []
    for case in CASES:
        for seed in SEEDS:
            initial = [indexed[case, m, seed]['checkpoints'][0] for m in METHODS]
            if any(c['queries'] != 16 for c in initial):
                raise ValueError('Missing common initialization checkpoint')
            if max(c['hypervolume'] for c in initial)-min(c['hypervolume'] for c in initial) > 1e-8:
                raise ValueError('Initialization metrics differ between paired methods')
        for method in METHODS:
            group = [indexed[case, method, s] for s in SEEDS]
            summaries.append(dict(case=case, method=method, seed_order=list(SEEDS),
                completed=sum(r['status'] == 'complete_query_budget' for r in group),
                capped=sum(r['status'] == 'stopped_at_limit' for r in group),
                queries=distribution([r['queries'] for r in group]),
                final_hypervolume=distribution([r['final_metrics']['hypervolume'] for r in group]),
                hypervolume_gain_from_initial=distribution([r['final_metrics']['hypervolume']-r['checkpoints'][0]['hypervolume'] for r in group]),
                marginal_temperature_gain_c=distribution([r['checkpoints'][0]['best_peak_c']-r['final_metrics']['best_peak_c'] for r in group]),
                marginal_span_gain_mm=distribution([r['checkpoints'][0]['best_centre_span_mm']-r['final_metrics']['best_centre_span_mm'] for r in group]),
                elapsed_seconds=distribution([r['elapsed_seconds'] for r in group]),
                proposals=distribution([r['proposals'] for r in group]),
                illegal_proposal_fraction=distribution([r['illegal_proposals']/r['proposals'] for r in group]),
                legal_evaluation_cache_fraction=distribution([r['cache_hits']/(r['queries']+r['cache_hits']) for r in group]),
                outside_reference=distribution([r['final_metrics']['archive_points_outside_reference'] for r in group])))
            if method != 'random':
                differences = [indexed[case, method, s]['final_metrics']['hypervolume']-
                               indexed[case, 'random', s]['final_metrics']['hypervolume'] for s in SEEDS]
                paired.append(dict(case=case, method=method, reference='random', seed_order=list(SEEDS),
                    final_hypervolume_difference=distribution(differences),
                    wins=sum(v > 1e-10 for v in differences), ties=sum(abs(v) <= 1e-10 for v in differences),
                    losses=sum(v < -1e-10 for v in differences),
                    both_completed=[indexed[case, method, s]['status'] == indexed[case, 'random', s]['status'] == 'complete_query_budget' for s in SEEDS]))
    fronts = {case: pooled_front([r for r in records if r['case'] == case]) for case in CASES}
    return dict(status='complete_pilot_descriptive_analysis', synthetic_fixture=data.get('synthetic_fixture', False),
                summaries=summaries, paired_vs_random=paired,
                empirical_pooled_fronts=fronts,
                scope='five paired seeds; descriptive ranges, not confidence intervals or significance; marginal single-objective gains need not coexist in one layout; capped runs retained at actual query count')


def figures(data, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    colors = dict(random='#3977b3', sa='#bd5d2a', nsga2='#278368')
    names = dict(random='Random', sa='Multi-weight SA', nsga2='NSGA-II')
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), layout='constrained')
    pareto_fig, pareto_axes = plt.subplots(1, 3, figsize=(13, 4.1), layout='constrained')
    for column, case in enumerate(CASES):
        ax, cost_ax, pareto_ax = axes[0, column], axes[1, column], pareto_axes[column]
        for method in METHODS:
            group = sorted([r for r in data['records'] if r['case'] == case and r['method'] == method], key=lambda r: r['seed'])
            color = colors[method]
            for row in group:
                checkpoints = list(row['checkpoints'])
                if checkpoints[-1]['queries'] != row['queries']:
                    checkpoints.append(dict(queries=row['queries'], **row['final_metrics']))
                ax.plot([c['queries'] for c in checkpoints], [c['hypervolume'] for c in checkpoints],
                        color=color, alpha=.20, linewidth=.8)
                marker = 'x' if row['status'] == 'stopped_at_limit' else 'o'
                cost_ax.scatter(row['elapsed_seconds'], row['final_metrics']['hypervolume'],
                                color=color, marker=marker, s=30, alpha=.8)
                front = [row['points'][i] for i in row['final_metrics']['archive_query_indices']]
                pareto_ax.scatter([p['centre_span_mm'] for p in front], [p['peak_c'] for p in front],
                                  s=15, alpha=.4, color=color)
            xs, medians, lows, highs = [], [], [], []
            for query in (16, 32, 64):
                observed = [c['hypervolume'] for r in group for c in r['checkpoints'] if c['queries'] == query]
                # Avoid hiding capped runs through survivor-only averages.
                if len(observed) == 5:
                    xs.append(query)
                    medians.append(statistics.median(observed))
                    lows.append(min(observed))
                    highs.append(max(observed))
            ax.plot(xs, medians, color=color, marker='o', label=names[method], linewidth=1.8)
            ax.fill_between(xs, lows, highs, color=color, alpha=.10)
            pareto_ax.scatter([], [], color=color, s=20, label=names[method])
        pooled = pooled_front([r for r in data['records'] if r['case'] == case])
        representatives = [b['members'][0] for b in pooled]
        pareto_ax.scatter([p['centre_span_mm'] for p in representatives], [p['peak_c'] for p in representatives],
                          marker='x', color='black', s=24, linewidths=.8, label='Empirical pooled front')
        ax.set(title=case, xlabel='Distinct thermal queries (initialization included)', ylabel='Hypervolume')
        ax.set_xticks([16, 32, 64])
        cost_ax.set(xlabel='Measured elapsed seconds (x = capped)', ylabel='Final hypervolume')
        pareto_ax.set(title=case, xlabel='Demand-weighted centre span (mm)', ylabel='Peak temperature (C)')
        for axis in (ax, cost_ax, pareto_ax):
            axis.spines[['top', 'right']].set_visible(False)
            axis.grid(alpha=.15)
    axes[0, 0].legend(frameon=False, fontsize=8)
    pareto_axes[0].legend(frameon=False, fontsize=8)
    title = 'Pilot: five paired seeds; median and full range (not confidence intervals)'
    if data.get('synthetic_fixture'):
        title = 'SYNTHETIC TEST DATA — NOT EXPERIMENT RESULTS'
    fig.suptitle(title)
    pareto_fig.suptitle('SYNTHETIC TEST DATA — NOT EXPERIMENT RESULTS' if data.get('synthetic_fixture') else
                        'Final per-run Pareto archives; empirical points, not global optima')
    for extension in ('.png', '.pdf'):
        fig.savefig(output.with_name(output.name+'-quality-cost').with_suffix(extension), dpi=180)
        pareto_fig.savefig(output.with_name(output.name+'-pareto').with_suffix(extension), dpi=180)
    plt.close(fig)
    plt.close(pareto_fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New output stem')
    args = parser.parse_args()
    raw = source_bytes(args.input)
    data = json.loads(raw)
    result = analyze(data)
    result['verified_evidence_sha256'] = hashlib.sha256(raw).hexdigest()
    with args.output.with_suffix('.json').open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    figures(data, args.output)
    print(json.dumps(result['paired_vs_random'], indent=2))


if __name__ == '__main__':
    main()
