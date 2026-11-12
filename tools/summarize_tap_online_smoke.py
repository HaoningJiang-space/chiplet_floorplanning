"""Check real online smoke accounting before publishing compact evidence."""
import argparse
import hashlib
import json
from pathlib import Path
from build_tap_ihp_endpoints import source_bytes
from diagnose_tap_sensitivity import thermal_key
from freeze_tap_geometry import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rng-regression', action='store_true', help='Verify only the v2 Ascend Random regression')
    parser.add_argument('--state-regression', action='store_true', help='Verify only the v3 Ascend SA regression')
    args = parser.parse_args()
    raw_plan = source_bytes(args.plan)
    plan = json.loads(raw_plan)
    expected = [('ascend910', m) for m in ('random', 'sa', 'nsga2')]
    expected += [('micro150', 'nsga2'), ('multigpu', 'nsga2')]
    if args.rng_regression:
        expected = [('ascend910', 'random')]
    if args.state_regression:
        expected = [('ascend910', 'sa')]
    records = []
    for name, method in expected:
        raw = source_bytes(args.root/f'{name}-{method}'/'result.json')
        r = json.loads(raw)
        if r['status'] != 'complete_query_budget' or not r['smoke_only'] or r['queries'] != 32:
            raise ValueError('Incomplete or non-smoke trial')
        if r['plan_sha256'] != hashlib.sha256(raw_plan).hexdigest():
            raise ValueError('Wrong plan')
        if (args.rng_regression or args.state_regression) and r.get('search_seed') != r['seed']+1000000:
            raise ValueError('Search stream was not separated')
        entry = next(c for c in plan['cases'] if c['domain']['name'] == name)
        initial = next(i for i in entry['initializations'] if i['seed'] == r['seed'])
        keys = [thermal_key(row['placement']) for row in r['rows']]
        if len(set(keys)) != 32 or keys[:16] != [thermal_key(p) for p in initial['placements']]:
            raise ValueError('Unique-query or shared-initialization mismatch')
        for row in r['rows']:
            verify(entry['domain'], row['placement'])
            if not row['thermal']['numerical_admission_passed']:
                raise ValueError('Unadmitted query')
        statuses = [e['status'] for e in r['events']]
        if (r['proposals'] != len(statuses) or statuses.count('thermal_evaluated') != 32
                or statuses.count('cache_hit') != r['cache_hits']
                or statuses.count('geometry_rejected') != r['illegal_proposals']
                or r['proposals'] != 32+r['cache_hits']+r['illegal_proposals']
                or r['solve_attempts'] != 32):
            raise ValueError('Accounting mismatch')
        keep = ('case', 'method', 'seed', 'status', 'budget', 'queries', 'solve_attempts',
                'proposals', 'illegal_proposals', 'cache_hits', 'generations',
                'construction_candidate_checks', 'geometry_seconds', 'solve_seconds',
                'elapsed_seconds', 'checkpoints', 'final_metrics', 'timing_scope')
        records.append(dict(raw_result_sha256=hashlib.sha256(raw).hexdigest(),
                            search_seed=r.get('search_seed', r['seed']), **{k: r[k] for k in keep}))
    result = dict(status='state_regression_verified' if args.state_regression else
                  'rng_regression_verified' if args.rng_regression else 'five_real_smoke_trials_verified',
                  plan_sha256=hashlib.sha256(raw_plan).hexdigest(),
                  total_hits_queries=32*len(expected), records=records,
                  scope='execution and accounting smoke only; no method-performance conclusion')
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps([dict(case=r['case'], method=r['method'], queries=r['queries'],
                          proposals=r['proposals'], cache_hits=r['cache_hits'], illegal=r['illegal_proposals'])
                      for r in records], indent=2))


if __name__ == '__main__':
    main()
