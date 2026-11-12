"""Local shared-clock topology, fanout, early/late and complete path validation."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
from time import perf_counter

from validation.measured_sources import digest
from validation.sources import git_revision, write_json
from validation.multilane_oracle import Network, delay_pair, expected, scenarios
from validation.multilane_fixture import libraries, netlist, script
from validation.multilane_report import extract


def compare(paths, c, min_max, correlated):
    errors, records = [], {}
    max_cap_error = 0.
    for key, actual in paths.items():
        receiver, lane, check, transition = key.split('_')
        receiver, lane = int(receiver), int(lane)
        reference = expected(c, receiver, lane, check, transition, min_max, correlated)
        shift = c.period_ns if check == 'hold' else 0.
        normalized = {}
        for field in ('launch_edge_ns', 'capture_edge_ns', 'launch_arrival_ns', 'data_arrival_ns', 'capture_arrival_ns', 'required_ns', 'slack_ns'):
            normalized[field] = actual[field]-(0. if field == 'slack_ns' else shift)
            errors.append(abs(normalized[field]-reference[field]))
        errors.append(abs(actual['signed_common_path_correction_ns']-(1 if check=='setup' else -1)*reference['common_path_correction_ns']))
        if correlated:
            errors.append(abs(actual['slack_ns']-reference['correlated_root_enumerated_slack_ns']))
        early_data, early_clock = min_max and check=='hold', min_max and check=='setup'
        i = ('rise','fall').index(transition)
        # Increment checks include the shared root twice as two distinct edge
        # observations, while its physical fanout is summed only once.
        delays = dict(root_launch=delay_pair(c,'root',early_data)[0], bank=delay_pair(c,'bank',early_data)[0],
            cq=delay_pair(c,'cq',early_data)[i], data=c.data(receiver,lane)[i]*(.7 if early_data else 1.),
            root_capture=delay_pair(c,'root',early_clock)[1], trunk=delay_pair(c,'trunk',early_clock)[1],
            branch=c.branch(receiver)[1]*(.7 if early_clock else 1.), inverter=delay_pair(c,'inverter',early_clock)[0])
        caps = dict(root_launch=.01*(c.receivers+1), root_capture=.01*(c.receivers+1),
                    bank=.01*c.lanes, cq=.01, data=.01, trunk=.01*c.receivers, branch=.01, inverter=.01*c.lanes)
        for name, value in delays.items():
            pin = actual['pins'][name]
            errors += [abs(pin['delay_ns']-value), abs(pin['slew_ns']-.1)]
            if pin['cap_pf'] is None:
                raise ValueError(key+': missing physical fanout capacitance')
            max_cap_error = max(max_cap_error, abs(pin['cap_pf']-caps[name]))
        records[key] = dict(expected=reference, normalized_observed=normalized,
                            signed_common_path_correction_ns=actual['signed_common_path_correction_ns'], pins=actual['pins'])
    if max(errors) > 1e-5 or max_cap_error > 1e-6:
        raise ValueError(f'event/fanout mismatch: time={max(errors)} ns cap={max_cap_error} pF')
    return dict(max_time_error_ns=max(errors), max_capacitance_error_pf=max_cap_error,
                checked_time_fields=len(errors), checked_paths=len(records), paths=records)


def run_case(sta, folder, c, min_max=False, correlated=False, mutation=None):
    folder.mkdir()
    inputs = dict(fixture_lib=libraries(c,mutation=mutation), fabric_v=netlist(c), run_tcl=script(c,min_max,correlated,mutation))
    if min_max:
        inputs['early_lib'] = libraries(c,True,mutation)
    hashes = {}
    for key, value in inputs.items():
        name = key.replace('_','.')
        path = folder/name; path.write_bytes(value.encode('utf-8')); hashes[name] = digest(path)
    result = dict(model=asdict(c), min_max=min_max, correlated_root=correlated, mutation=mutation, input_sha256=hashes,
                  physical_d2d_qualified=False, routing_qualified=False, thermal_feedback_qualified=False)
    start = perf_counter()
    run = subprocess.run([str(sta),'-no_init','-exit','run.tcl'],cwd=folder,capture_output=True,text=True,timeout=120)
    result.update(returncode=run.returncode, elapsed_s=perf_counter()-start)
    log = run.stdout+run.stderr
    (folder/'sta.log').write_text(log)
    result['log_sha256'] = digest(folder/'sta.log')
    try:
        if run.returncode:
            raise ValueError('OpenSTA execution failed')
        result.update(compare(extract(log,c.receivers,c.lanes),c,min_max,correlated))
        result['numerical_contract_accepted'] = True
        result['setup_pass'] = all(v['normalized_observed']['slack_ns'] >= 0 for k,v in result['paths'].items() if '_setup_' in k)
        result['hold_pass'] = all(v['normalized_observed']['slack_ns'] >= 0 for k,v in result['paths'].items() if '_hold_' in k)
    except ValueError as error:
        result.update(numerical_contract_accepted=False, rejection_reason=str(error))
    write_json(folder/'receipt.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sta',type=Path,default=Path('local/upstream/OpenSTA/app/sta.exe'))
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args(); sta=args.sta.resolve(strict=True)
    args.output.mkdir(parents=True,exist_ok=False)
    paths = [Path(__file__)]+list(Path('tools/validation').glob('multilane_*.py'))+[
        Path('tools/validation/timing_fixture.py'), Path('tools/validation/timing_oracle.py'),
        Path('src/chiplet_floorplanning/network_reports.py'),
        Path('tools/validation/timing_report.py'), Path('docs/multilane-validation-plan.md')]
    frozen = dict(git=git_revision(Path('.')), code_sha256={str(p):digest(p) for p in paths},
                  executable_sha256=digest(sta), sta_version=subprocess.check_output([str(sta),'-version'],text=True).strip(),
                  cases={k:dict(model=asdict(c),min_max=m,correlated_root=r) for k,(c,m,r) in scenarios().items()})
    write_json(args.output/'frozen-inputs.json',frozen)
    report = dict(frozen,cases={},negative_controls={},physical_d2d_qualified=False,complete=False)
    for name,(c,m,r) in scenarios().items():
        report['cases'][name] = run_case(sta,args.output/name,c,m,r)
        write_json(args.output/'report.json',report)
        print(name,report['cases'][name]['numerical_contract_accepted'],flush=True)
    for mutation in ('missing_capture_clock','wrong_capture_polarity','missing_last_lane','wrong_lane_endpoint','overloaded_bank'):
        report['negative_controls'][mutation] = run_case(sta,args.output/mutation,Network(receivers=3),mutation=mutation)
    checks = {k:v['numerical_contract_accepted'] for k,v in report['cases'].items()}
    checks.update({'reject_'+k:not v['numerical_contract_accepted'] for k,v in report['negative_controls'].items()})
    checks['setup_failure_preserved'] = report['cases']['setup_failure'].get('setup_pass') is False
    checks['hold_failure_preserved'] = report['cases']['hold_failure'].get('hold_pass') is False
    report.update(complete=True, checks=checks, numerical_checks_passed=all(checks.values()))
    write_json(args.output/'report.json',report)
    print(json.dumps(checks,indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
