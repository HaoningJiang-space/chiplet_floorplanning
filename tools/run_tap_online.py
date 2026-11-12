"""Freeze initial conditions, then run one isolated local baseline trial."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
from build_tap_ihp_endpoints import source_bytes
from diagnose_tap_sensitivity import thermal_key
from tap_online import Space, run_policy
from prepare_tap_fv import make_case
from solve_tap_fv_hits import run
from chiplet_floorplanning.model import parse_case

HITS_COMMIT = 'be59924de3f0c1a3d6d134aea411d1264cfa64c6'
SOURCES = ('tools/tap_online.py', 'tools/run_tap_online.py', 'tools/prepare_tap_fv.py',
           'tools/solve_tap_fv_hits.py', 'tools/freeze_tap_geometry.py',
           'src/chiplet_floorplanning/package.py', 'src/chiplet_floorplanning/power.py',
           'src/chiplet_floorplanning/model.py', 'docs/tap-online-protocol.md',
           'docs/evidence/tap-geometry-domains.json', 'docs/evidence/tap-sensitivity.json')


def hashes():
    return {p: hashlib.sha256(source_bytes(p)).hexdigest() for p in SOURCES}


def freeze(path):
    geometry = json.loads(source_bytes('docs/evidence/tap-geometry-domains.json'))
    diagnostic = json.loads(source_bytes('docs/evidence/tap-sensitivity.json'))
    plan = dict(protocol='tap-online-v1', budget=64, proposal_cap=10000, population=16,
                seeds=list(range(2026111200, 2026111205)), hits_commit=HITS_COMMIT,
                source_sha256=hashes(), cases=[])
    for entry in geometry['cases']:
        domain = entry['domain']
        rows = next(c['rows'] for c in diagnostic['cases'] if c['case'] == domain['name'])
        temperatures = [r['thermal']['peak_power_layer_c'] for r in rows]
        spans = [r['centre_span_mm'] for r in rows]
        scale = dict(temperature_origin_c=min(temperatures), temperature_scale_k=max(temperatures)-min(temperatures),
                     span_origin_mm=min(spans), span_scale_mm=max(spans)-min(spans), hypervolume_reference=[1.2, 1.2])
        if min(scale['temperature_scale_k'], scale['span_scale_mm']) <= 0:
            raise ValueError('Degenerate diagnostic scale')
        case = dict(domain=domain, scale=scale, initializations=[])
        space = Space(domain)
        for seed in plan['seeds']:
            rng = random.Random(seed)
            initial = [entry['witness']['placement']]
            seen = {thermal_key(initial[0])}
            attempts = 0
            checks = space.construction_candidate_checks
            while len(initial) < 16 and attempts < 10000:
                attempts += 1
                placement = space.construct(rng)
                if placement is not None and thermal_key(placement) not in seen:
                    initial.append(placement)
                    seen.add(thermal_key(placement))
            if len(initial) != 16:
                raise ValueError('Initialization construction exhausted')
            case['initializations'].append(dict(seed=seed, placements=initial,
                construction_attempts=attempts, construction_candidate_checks=space.construction_candidate_checks-checks))
        plan['cases'].append(case)
    with path.open('x', encoding='utf-8') as f:
        json.dump(plan, f, indent=2)
        f.write('\n')


def execute(args):
    raw = source_bytes(args.plan)
    plan = json.loads(raw)
    if hashes() != plan['source_sha256']:
        raise ValueError('Frozen implementation/input hash mismatch')
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
    result = run_policy(entry['domain'], initial['placements'], entry['scale'], args.method,
                        args.seed, solve, budget=budget, proposal_cap=plan['proposal_cap'])
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
    parser.add_argument('--hits', type=Path)
    parser.add_argument('--case', choices=('ascend910', 'micro150', 'multigpu'))
    parser.add_argument('--seed', type=int)
    parser.add_argument('--method', choices=('random', 'sa', 'nsga2'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--smoke-budget', type=int)
    args = parser.parse_args()
    if args.freeze:
        freeze(args.plan)
    else:
        if any(v is None for v in (args.hits, args.case, args.seed, args.method, args.output)):
            parser.error('Execution requires hits, case, seed, method and output')
        execute(args)
