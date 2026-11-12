"""Freeze initial conditions, then run one isolated local baseline trial."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
from build_tap_ihp_endpoints import source_bytes
from tap_online import run_policy
from tap_published_moves import run_tap_policy
from tap_r3_metrics import diagnostic_contract
from prepare_tap_fv import make_case
from solve_tap_fv_hits import run
from chiplet_floorplanning.model import parse_case

HITS_COMMIT = 'be59924de3f0c1a3d6d134aea411d1264cfa64c6'
SOURCES = ('tools/tap_online.py', 'tools/run_tap_online.py', 'tools/prepare_tap_fv.py',
           'tools/diagnose_tap_sensitivity.py', 'tools/build_tap_algorithm_oracle.py',
           'tools/build_tap_ihp_endpoints.py',
           'tools/solve_tap_fv_hits.py', 'tools/freeze_tap_geometry.py',
           'src/chiplet_floorplanning/package.py', 'src/chiplet_floorplanning/power.py',
           'src/chiplet_floorplanning/model.py', 'docs/tap-online-protocol.md',
           'src/chiplet_floorplanning/mesh.py',
           'docs/evidence/tap-geometry-domains.json', 'docs/evidence/tap-sensitivity.json')
R3_SOURCES = SOURCES + ('tools/tap_r3_metrics.py', 'tools/tap_published_moves.py',
                        'tools/run_tap_online_batch.py', 'tools/report_tap_physical.py',
                        'tools/verify_tap_online_pilot.py', 'docs/tap-r3-metrics.md',
                        'docs/tap-r3-conditional-mutation.md', 'docs/tap-r3-protocol.md')


def hashes(sources=SOURCES):
    return {p: hashlib.sha256(source_bytes(p)).hexdigest() for p in sources}


def freeze(path, reference_path=Path('docs/evidence/tap-online-plan-v4.json')):
    reference_raw = source_bytes(reference_path)
    reference = json.loads(reference_raw)
    diagnostic = json.loads(source_bytes('docs/evidence/tap-sensitivity.json'))
    plan = dict(protocol='tap-online-r3-physical-v1', budget=reference['budget'],
                proposal_cap=reference['proposal_cap'], population=16,
                seeds=reference['seeds'][:3], hits_commit=HITS_COMMIT,
                methods=['random', 'sa', 'nsga2', 'tap_sa', 'nsga2_legal'],
                methods_to_run=['tap_sa', 'nsga2_legal'],
                reference_plan_sha256=hashlib.sha256(reference_raw).hexdigest(),
                reused_evidence_sha256=hashlib.sha256(source_bytes('docs/evidence/tap-online-pilot-v4.json')).hexdigest(),
                source_sha256=hashes(R3_SOURCES), cases=[])
    for entry in reference['cases']:
        case = copy.deepcopy(entry)
        case['initializations'] = [i for i in case['initializations'] if i['seed'] in plan['seeds']]
        rows = next(c['rows'] for c in diagnostic['cases'] if c['case'] == case['domain']['name'])
        case['comparison'] = diagnostic_contract(rows)
        plan['cases'].append(case)
    with path.open('x', encoding='utf-8') as f:
        json.dump(plan, f, indent=2)
        f.write('\n')


def execute(args):
    raw = source_bytes(args.plan)
    plan = json.loads(raw)
    if plan['protocol'] != 'tap-online-r3-physical-v1':
        raise ValueError('Historical v4 execution requires its recorded code revision; freeze a new R3 plan')
    if hashes(R3_SOURCES) != plan['source_sha256']:
        raise ValueError('Frozen implementation/input hash mismatch')
    if args.method not in plan['methods']:
        raise ValueError('Method is not declared in the plan')
    sha = subprocess.check_output(['git', '-C', str(args.hits), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(args.hits), 'status', '--porcelain'], text=True).strip()
    if sha != plan['hits_commit'] or dirty:
        raise ValueError('HiTS must match the clean pinned source')
    entry = next(c for c in plan['cases'] if c['domain']['name'] == args.case)
    initial = next(i for i in entry['initializations'] if i['seed'] == args.seed)
    args.output.mkdir(parents=True, exist_ok=False)
    counter = 0
    def solve(placement):
        nonlocal counter
        summary, _, _, _ = run(parse_case(make_case(entry['domain'], placement)), args.hits)
        (args.output/f'query-{counter:03d}.json').write_text(json.dumps(dict(placement=placement, thermal=summary)), encoding='utf-8')
        counter += 1
        print(args.case, args.method, counter, summary['peak_power_layer_c'], flush=True)
        return summary
    budget = args.smoke_budget or plan['budget']
    if args.smoke_budget is not None and not 16 <= budget < plan['budget']:
        raise ValueError('Smoke budget must be 16..63')
    kwargs = dict(budget=budget, proposal_cap=plan['proposal_cap'], comparison=entry['comparison'])
    if args.method == 'tap_sa':
        result = run_tap_policy(entry['domain'], initial['placements'], entry['scale'], args.seed, solve, **kwargs)
    else:
        result = run_policy(entry['domain'], initial['placements'], entry['scale'], args.method, args.seed, solve, **kwargs)
    result.update(case=args.case, scale=entry['scale'], smoke_only=args.smoke_budget is not None,
                  plan_sha256=hashlib.sha256(raw).hexdigest(), hits_commit=sha,
                  initialization_construction=initial['construction_attempts'],
                  initialization_candidate_checks=initial['construction_candidate_checks'],
                  timing_scope='online elapsed includes per-run domain setup and all evaluation/reference checks; offline manifest construction separately counted')
    (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    if result['status'] != 'complete_query_budget':
        raise SystemExit(result['status']+': '+str(result['reason']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--reference-plan', type=Path, default=Path('docs/evidence/tap-online-plan-v4.json'))
    parser.add_argument('--hits', type=Path)
    parser.add_argument('--case', choices=('ascend910', 'micro150', 'multigpu'))
    parser.add_argument('--seed', type=int)
    parser.add_argument('--method', choices=('random', 'sa', 'nsga2', 'tap_sa', 'nsga2_legal'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--smoke-budget', type=int)
    args = parser.parse_args()
    if args.freeze:
        freeze(args.plan, args.reference_plan)
    else:
        if any(v is None for v in (args.hits, args.case, args.seed, args.method, args.output)):
            parser.error('Execution requires hits, case, seed, method and output')
        execute(args)
