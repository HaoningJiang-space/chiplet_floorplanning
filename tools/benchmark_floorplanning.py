"""Frozen finite placement benchmark using the same paired electrothermal evaluator."""

import argparse
import copy
import json
from pathlib import Path
import time

from chiplet_floorplanning.characterization import digest
from chiplet_floorplanning.decision import summarize_decisions
from chiplet_floorplanning.floorplanning import evaluate, write_json
from validation.sources import git_revision, LOCK
from validation.decision_evidence import verify_pdk


def domain():
    result = {}
    for slot, x in enumerate((.5, 2.5, 4.5)):
        for angle in (0, 90, 180, 270):
            result[f'slot{slot}_rot{angle}'] = {
                'tx': dict(x=x, y=3., rotation_deg=angle),
                'rx0': dict(x=5., y=.5, rotation_deg=angle),
                'rx1': dict(x=7., y=5., rotation_deg=(-angle)%360)}
    return result


def profile(base, name):
    cfg = copy.deepcopy(base)
    if name=='tx_power_125pct':
        for block in cfg['design']['chiplets'][0]['blocks']:
            block['power_w'] *= 1.25
    elif name=='cooling_800':
        cfg['design']['thermal']['top_h_w_m2k'] = 800.
    elif name=='package_load_25ff':
        cfg['electrical']['package_input_load_pf'] = .025
    elif name!='nominal':
        raise ValueError('unknown predeclared operating condition')
    return cfg


def compact(row):
    result = {k: row[k] for k in ('id', 'layout_id', 'profile', 'policy', 'status', 'geometry_feasible', 'routing_status')}
    result['peak_c'] = row.get('thermal', {}).get('peak_c')
    result['energy_balance_error_w'] = row.get('thermal', {}).get('energy_balance_error_w')
    result['reason'] = row.get('reason')
    result['timing'] = {mode: {k: value[k] for k in ('status', 'reason', 'worst_setup_ns', 'worst_hold_ns',
                        'critical_setup', 'critical_hold', 'timing_feasible', 'table_audit') if k in value}
                        for mode, value in row.get('timing', {}).items()}
    result['checked_paths'] = sum(len(t.get('paths', {})) for t in row.get('timing', {}).values())
    changes = list(row.get('feedback_slack_change_ns', {}).values())
    result['feedback_slack_change_range_ns'] = [min(changes), max(changes)] if changes else None
    if 'routing_audit' in row:
        result['route_length_mm'] = sum(n['unique_total_length_mm'] for n in row['routing_audit']['nets'].values())
        result['clock_unique_length_mm'] = row['routing_audit']['nets']['forwarded_clock']['unique_total_length_mm']
        result['occupied_nodes'] = row['routing_audit']['occupied_node_count']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration', type=Path, default=Path('examples/three_chiplet_decision.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sta', type=Path, default=Path('local/upstream/OpenSTA/app/sta.exe'))
    parser.add_argument('--model-root', type=Path, default=Path('local/pdk-v03'))
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    base = json.loads(args.configuration.read_text()); layouts = domain()
    profiles = ('nominal', 'tx_power_125pct', 'cooling_800', 'package_load_25ff')
    names = [n['id'] for n in base['design']['links'] if n['kind']=='data']
    orders = {'data_first': names+['forwarded_clock'], 'clock_first': ['forwarded_clock']+names}
    code = list(Path('src/chiplet_floorplanning').glob('*.py'))+[Path(__file__), Path('tools/validation/sources.py'),
                                                              Path('tools/validation/decision_evidence.py'), LOCK]
    pdk_manifest = {r['path']: r['sha256'] for r in json.loads(LOCK.read_text())['files']
                    if r['path'].startswith('pdk-v03/')}
    frozen = dict(git=git_revision(Path('.')), source_sha256={str(p): digest(p) for p in code},
                  configuration_sha256=digest(args.configuration), executable_sha256=digest(args.sta),
                  pdk_source_sha256=verify_pdk(args.model_root, pdk_manifest),
                  layouts=layouts, profiles={n: profile(base, n) for n in profiles}, route_orders=orders,
                  domain_size=len(layouts)*len(profiles)*len(orders), started_after_domain_freeze=True, physical_interface_qualified=False)
    write_json(args.output/'frozen-inputs.json', frozen)
    report = dict(complete=False, frozen_inputs_sha256=digest(args.output/'frozen-inputs.json'),
                  cases=[], profiles={}, physical_interface_qualified=False)
    all_rows = []; started = time.perf_counter()
    for condition in profiles:
        rows = []
        for layout_id, layout in layouts.items():
            for policy, order in orders.items():
                name = condition+'_'+layout_id+'_'+policy
                cfg = profile(base, condition); cfg['routing']['order'] = order
                cfg['runtime'] = dict(sta=str(args.sta), model_root=str(args.model_root), output=str(args.output/name))
                row = evaluate(layout, cfg)
                row.update(id=name, layout_id=layout_id, profile=condition, policy=policy)
                rows.append(row); all_rows.append(row); report['cases'].append(compact(row))
                write_json(args.output/'report.json', report)
                print(len(all_rows), '/', frozen['domain_size'], name, row['status'],
                      row.get('thermal', {}).get('peak_c'), flush=True)
        report['profiles'][condition] = summarize_decisions(rows, expected_layout_ids=layouts, expected_profile=condition)
        write_json(args.output/'report.json', report)
    # Refine the best and nearest distinct thermal competitor, preserving their
    # exact route policy. This diagnoses numerical difference, not model error.
    nominal = [r for r in all_rows if r['profile']=='nominal' and r.get('feasible_feedback')]
    ordered = sorted(nominal, key=lambda r: (r['thermal']['peak_c'], r['id']))
    selected = []
    for row in ordered:
        if row['layout_id'] not in [r['layout_id'] for r in selected]:
            selected.append(row)
        if len(selected)==2:
            break
    report['paired_refinement'] = []
    for factor in (2, 4):
        for original in selected:
            cfg = profile(base, 'nominal'); cfg['routing']['order'] = orders[original['policy']]
            cfg['grid'] = {**base['design']['grid'], 'nx': base['design']['grid']['nx']*factor,
                           'ny': base['design']['grid']['ny']*factor}
            name = f'refine{factor}_'+original['layout_id']+'_'+original['policy']
            cfg['runtime'] = dict(sta=str(args.sta), model_root=str(args.model_root), output=str(args.output/name))
            row = evaluate(layouts[original['layout_id']], cfg)
            row.update(id=name, layout_id=original['layout_id'], profile='nominal', policy=original['policy'])
            report['paired_refinement'].append(dict(factor=factor, **compact(row)))
            write_json(args.output/'report.json', report)
            print(name, row['status'], row.get('thermal', {}).get('peak_c'), flush=True)
    report.update(complete=True, elapsed_s=time.perf_counter()-started,
                  checked_paths=sum(r['checked_paths'] for r in report['cases']+report['paired_refinement']))
    write_json(args.output/'report.json', report)
    print('Complete', report['checked_paths'], 'paths', flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
