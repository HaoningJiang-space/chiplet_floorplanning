"""Compare attained layouts at fixed physical budgets, reusing thermal evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from build_tap_ihp_endpoints import source_bytes
from tap_r3_metrics import constrained_profile, paired_profiles

CONTRASTS = (('sa', 'random'), ('nsga2', 'random'), ('tap_sa', 'nsga2'),
             ('nsga2_legal', 'nsga2'), ('nsga2_legal', 'tap_sa'))


def aggregate(pairs, axis, anchor):
    entries = [next(p for p in pair[axis] if p['id'] == anchor) for pair in pairs]
    field = 'temperature_gain_k' if axis == 'temperature_at_span_budget' else 'span_reduction_percent'
    values = [p[field] for p in entries]
    attained = [v for v in values if v is not None]
    tolerance = 1e-6 if field == 'temperature_gain_k' else 1e-9
    return dict(id=anchor, metric=field, paired_values=values, paired_statuses=[p['status'] for p in entries],
                both_attained=len(attained), total_pairs=len(entries),
                candidate_only_attained=sum(p['status'] == 'candidate_only_attained' for p in entries),
                baseline_only_attained=sum(p['status'] == 'baseline_only_attained' for p in entries),
                neither_attained=sum(p['status'] == 'neither_attained' for p in entries),
                conditional_median=statistics.median(attained) if attained else None,
                conditional_minimum=min(attained) if attained else None,
                conditional_maximum=max(attained) if attained else None,
                wins=sum(v > tolerance for v in attained), ties=sum(abs(v) <= tolerance for v in attained),
                losses=sum(v < -tolerance for v in attained))


def analyze(records, contracts):
    index = {(r['case'], r['method'], r['seed']): r for r in records}
    if len(index) != len(records):
        raise ValueError('Duplicate trial')
    cases = sorted({r['case'] for r in records})
    methods = sorted({r['method'] for r in records})
    seeds = sorted({r['seed'] for r in records})
    if set(index) != {(c, m, s) for c in cases for m in methods for s in seeds}:
        raise ValueError('Incomplete case/method/seed coverage')
    profiles, run_scores = {}, []
    for case in cases:
        for seed in seeds:
            groups = [index[case, m, seed] for m in methods]
            shared = groups[0]['points'][:16]
            if len(shared) != 16 or any(r['points'][:16] != shared for r in groups[1:]):
                raise ValueError('Paired initialization differs')
            for record in groups:
                points = record['points']
                if record['queries'] != len(points) or record['queries'] > 64:
                    raise ValueError('Query ledger mismatch')
                if record['status'] not in ('complete_query_budget', 'stopped_at_limit'):
                    raise ValueError('Failed/unknown run cannot be silently included as a completed comparison')
                if record['status'] == 'complete_query_budget' and len(points) != 64:
                    raise ValueError('Expected complete 64-query run')
                profile = constrained_profile(points, contracts[case])
                profiles[case, record['method'], seed] = profile
                run_scores.append(dict(case=case, method=record['method'], seed=seed,
                    status=record['status'], queries=len(points), physical_comparison=profile,
                    anytime=[dict(queries=n, **constrained_profile(points[:n], contracts[case]))
                             for n in sorted({n for n in (16, 32, 64) if n <= len(points)} | {len(points)})],
                    auxiliary_hypervolume=record['final_metrics']['hypervolume'],
                    effort={k: record[k] for k in ('proposals', 'cache_hits', 'illegal_proposals',
                            'elapsed_seconds', 'solve_seconds', 'geometry_seconds') if k in record}))
    contrasts = []
    for case in cases:
        for candidate, baseline in CONTRASTS:
            if candidate not in methods or baseline not in methods:
                continue
            pairs = [paired_profiles(profiles[case, candidate, s], profiles[case, baseline, s]) for s in seeds]
            contrasts.append(dict(case=case, candidate=candidate, baseline=baseline, seed_order=seeds,
                both_complete=[index[case, candidate, s]['status'] == index[case, baseline, s]['status'] == 'complete_query_budget'
                               for s in seeds],
                individual_pairs=pairs,
                temperature_at_span_budget=[aggregate(pairs, 'temperature_at_span_budget', a['id'])
                                            for a in contracts[case]['span_budgets']],
                span_at_temperature_cap=[aggregate(pairs, 'span_at_temperature_cap', a['id'])
                                         for a in contracts[case]['temperature_caps']]))
    return dict(schema='tap-physical-report-v1', cases=cases, methods=methods, seeds=seeds,
                contracts=contracts, runs=run_scores, contrasts=contrasts,
                interpretation='Positive gains favor candidate. Medians condition on both methods attaining the same constraint; always report attainment counts. No interpolation, global optimum or significance claim.')


def markdown(result):
    lines = ['# Layout quality at shared physical constraints', '', result['analysis_scope'], '',
             'Primary: minimum attained peak temperature under a common demand-weighted mean centre-span budget. '
             'Reverse comparison: minimum attained centre span under a common peak-temperature ceiling. '
             'These are centre-distance proxies, not routed wirelength or timing.', '',
             'Budgets are nearest-rank p25/p50/p75 of the earlier 20-layout sensitivity sample per case; '
             'the primary table uses p50. They are research anchors, not product limits. '
             'All methods share 16 initial queries within a 64-query allowance.', '',
             '| Case | Candidate / baseline | Span budget (mm) | Paired temperature gain (K), median [range] | Both attained | Win/tie/loss |',
             '| --- | --- | ---: | --- | ---: | --- |']
    def display(s):
        if s['conditional_median'] is None:
            return 'not attained'
        return f"{s['conditional_median']:+.4f} [{s['conditional_minimum']:+.4f}, {s['conditional_maximum']:+.4f}]"
    for c in result['contrasts']:
        contract = result['contracts'][c['case']]
        anchor = contract['primary_anchor']
        s = next(x for x in c['temperature_at_span_budget'] if x['id'] == anchor)
        limit = next(x['span_budget_mm'] for x in contract['span_budgets'] if x['id'] == anchor)
        lines.append(f"| {c['case']} | {c['candidate']} / {c['baseline']} | {limit:.4f} | {display(s)} | {s['both_attained']}/{s['total_pairs']} | {s['wins']}/{s['ties']}/{s['losses']} |")
    lines += ['', '| Case | Candidate / baseline | Temperature cap (C) | Paired span reduction (%), median [range] | Both attained |',
              '| --- | --- | ---: | --- | ---: |']
    for c in result['contrasts']:
        contract = result['contracts'][c['case']]
        anchor = contract['primary_anchor']
        s = next(x for x in c['span_at_temperature_cap'] if x['id'] == anchor)
        limit = next(x['temperature_cap_c'] for x in contract['temperature_caps'] if x['id'] == anchor)
        lines.append(f"| {c['case']} | {c['candidate']} / {c['baseline']} | {limit:.4f} | {display(s)} | {s['both_attained']}/{s['total_pairs']} |")
    lines += ['', 'Positive values favor the candidate. Numeric summaries include only pairs where both attained the constraint; '
              'missing attainment is never zero gain. JSON retains all three anchors, each paired value/status, selected layout '
              'query indices, actual temperature AND span, checkpoint profiles, completion status, auxiliary HV and effort. '
              'A selected query index refers to the corresponding case/method/seed record in the source evidence.', '',
              'HV summarizes Pareto coverage only. Separately best temperature and span are not a feasible joint design. '
              'Wall times are observations under workstation load, not controlled algorithm speedups.', '']
    return '\n'.join(lines)


def figure(result, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, len(result['cases']), figsize=(13, 4.3), squeeze=False, layout='constrained')
    for ax, case in zip(axes[0], result['cases']):
        for c in (c for c in result['contrasts'] if c['case'] == case):
            xs = [b['span_budget_mm'] for b in result['contracts'][case]['span_budgets']]
            for i, s in enumerate(c['temperature_at_span_budget']):
                vals = [v for v in s['paired_values'] if v is not None]
                ax.scatter([xs[i]]*len(vals), vals, s=10, alpha=.25, color=f'C{CONTRASTS.index((c["candidate"], c["baseline"]))}')
            # Points only: no invented layouts or values between budget anchors.
            ax.scatter(xs, [s['conditional_median'] if s['both_attained'] == s['total_pairs'] else float('nan')
                            for s in c['temperature_at_span_budget']], s=45,
                       color=f'C{CONTRASTS.index((c["candidate"], c["baseline"]))}',
                       label=f"{c['candidate']} - {c['baseline']}")
        ax.axhline(0, color='gray', linewidth=.8)
        ax.set(title=case, xlabel='Common centre-span budget (mm)', ylabel='Paired peak-temperature reduction (K)')
        ax.spines[['top', 'right']].set_visible(False)
        ax.grid(alpha=.15)
    axes[0, 0].legend(frameon=False, fontsize=8)
    fig.suptitle(f"Equal interconnect budgets: {len(result['seeds'])} paired seeds; dots = pairs, large dots = median when all attain")
    for suffix in ('.png', '.pdf'):
        fig.savefig(output.with_suffix(suffix), dpi=180)
    plt.close(fig)


def load_records(evidence, plan, batch_path=None, plan_sha=None):
    if evidence['status'] != 'complete_pilot_verified' or not evidence['policy_replay']:
        raise ValueError('Verified historical evidence required')
    if batch_path is None:
        if evidence['verified_runs'] != 45 or len(evidence['records']) != 45:
            raise ValueError('Preserve all 45 historical trials')
        return evidence['records']
    batch = json.loads((batch_path/'batch.json').read_text(encoding='utf-8'))
    if batch['status'] not in ('complete', 'complete_with_caps') or batch['plan_sha256'] != plan_sha:
        raise ValueError('Complete matching R3 batch required')
    records = [r for r in evidence['records'] if r['seed'] in plan['seeds']]
    for trial in batch['runs']:
        path = batch_path/f"{trial['case']}-{trial['seed']}-{trial['method']}"/'result.json'
        r = json.loads(path.read_text(encoding='utf-8'))
        entry = next(c for c in plan['cases'] if c['domain']['name'] == r['case'])
        if (any(r[k] != v for k, v in trial.items()) or r['smoke_only'] or r['budget'] != 64
                or r['plan_sha256'] != plan_sha or r['scale'] != entry['scale']):
            raise ValueError('Incompatible or development-only trial')
        from verify_tap_online_pilot import validate_run
        validate_run(r, entry, plan, replay=True)
        record = {k: v for k, v in r.items() if k not in ('rows', 'events', 'decisions', 'research_metrics')}
        record['points'] = [{k: p[k] for k in ('query_index', 'placement', 'peak_c', 'centre_span_mm')} for p in r['rows']]
        record['raw_result_sha256'] = hashlib.sha256(source_bytes(path)).hexdigest()
        records.append(record)
    expected = {(c['domain']['name'], m, s) for c in plan['cases'] for m in plan['methods'] for s in plan['seeds']}
    if {(r['case'], r['method'], r['seed']) for r in records} != expected or len(records) != len(expected):
        raise ValueError('Incomplete R3 evidence')
    return records


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--batch', type=Path, help='Complete R3 batch; omit for retrospective 45-run analysis')
    p.add_argument('--output', type=Path, required=True, help='New output stem')
    args = p.parse_args()
    raw, plan_raw = source_bytes(args.input), source_bytes(args.plan)
    evidence, plan = json.loads(raw), json.loads(plan_raw)
    if hashlib.sha256(raw).hexdigest() != plan['reused_evidence_sha256']:
        raise ValueError('Historical evidence hash mismatch')
    records = load_records(evidence, plan, args.batch, hashlib.sha256(plan_raw).hexdigest())
    result = analyze(records, {c['domain']['name']: c['comparison'] for c in plan['cases']})
    result.update(source_evidence_sha256=hashlib.sha256(raw).hexdigest(), plan_sha256=hashlib.sha256(plan_raw).hexdigest(),
                  analysis_scope='R3 comparison with predeclared physical anchors; historical baselines reused.' if args.batch else
                  'Retrospective reanalysis of the completed 45-run pilot: these physical anchors were chosen after that pilot. No new thermal solves or new seeds; original evidence remains unchanged.')
    if args.batch:
        result['source_records'] = records
    for suffix, contents in (('.json', json.dumps(result, indent=2)+'\n'), ('.md', markdown(result))):
        with args.output.with_suffix(suffix).open('x', encoding='utf-8') as f:
            f.write(contents)
    figure(result, args.output)
    print(markdown(result))


if __name__ == '__main__':
    main()
