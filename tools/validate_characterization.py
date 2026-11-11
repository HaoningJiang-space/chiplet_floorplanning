"""Public-library PVT and temperature controls; no physical signoff claim."""
import argparse
import json
from pathlib import Path
import re

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from chiplet_floorplanning.characterization import sky_instance_model, gf_instance_model, LANE_INSTANCES
from chiplet_floorplanning.cli import evaluate, source_revision
from chiplet_floorplanning.model import load_case
from chiplet_floorplanning.timing import run_timing
from prepare_characterization import prepare, SKY_CORNERS, GF_CORNERS


def compact(run):
    return {k: run[k] for k in ('status', 'setup_slack_ns', 'hold_slack_ns', 'libraries')}


def delta(a, b):
    return max(abs(a[key]-b[key]) for key in ('setup_slack_ns', 'hold_slack_ns'))


def delay_witness(root, log_path, temperature_c):
    """Independently query original endpoint tables at OpenSTA's slew/Ceff."""
    log = log_path.read_text()
    calc = log.split('DCALC_TX_DATA_BEGIN', 1)[1].split('DCALC_TX_DATA_END', 1)[0]
    record = {}
    for edge, symbol in [('rise', '^'), ('fall', 'v')]:
        section = calc.split(f'A {symbol} -> X {symbol}', 1)[1].split('................................', 1)[0]
        slew = float(re.search(r'input_net_transition = ([0-9.eE+-]+)', section)[1])
        ceff = float(re.search(r'total_output_net_capacitance = ([0-9.eE+-]+)', section)[1])
        actual = float(re.search(r'Delay = ([0-9.eE+-]+)', section)[1])
        endpoints = []
        for corner in ('ff_n40C_1v65', 'ff_100C_1v65'):
            cell = json.loads((root/f'sky_buf_8_{corner}.json').read_text())
            table = cell['pin,X']['timing'][f'cell_{edge},del_1_7_7']
            interpolator = RegularGridInterpolator((table['index_1'], table['index_2']), np.array(table['values']), bounds_error=True)
            endpoints.append(float(interpolator([[slew, ceff]])[0]))
        fraction = (temperature_c+40)/140
        expected = endpoints[0]+fraction*(endpoints[1]-endpoints[0])
        record[edge] = dict(input_slew_ns=slew, effective_cap_pf=ceff, original_endpoint_delays_ns=endpoints,
                            independently_interpolated_delay_ns=expected, opensta_delay_ns=actual,
                            absolute_error_ns=abs(expected-actual))
    path = log.split('Path Type: max', 1)[1].split('DCALC_TX_DATA_BEGIN', 1)[0]
    arrival = float(re.search(r'([0-9.eE+-]+)\s+data arrival time', path)[1])
    required = float(re.search(r'([0-9.eE+-]+)\s+data required time', path)[1])
    record.update(data_arrival_ns=arrival, data_required_ns=required, recomputed_setup_slack_ns=required-arrival)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('local'))
    parser.add_argument('--sta', type=Path, default=Path('local/upstream/OpenSTA/app/sta'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assembly = prepare(args.root)
    root, output = args.root/'pdk-v03', args.output
    output.mkdir(parents=True, exist_ok=False)
    case = load_case('examples/layered_two_chiplets.json')
    checks, pvt = {}, {}
    for sky in SKY_CORNERS:
        for gf in GF_CORNERS:
            key = sky+'__'+gf
            gf_path = args.root/'pdk/gf180_tt_1v8.lib' if gf == 'tt_025C_1v80' else root/f'gf_core_{gf}.lib'
            run = run_timing(case, output/key, args.sta, root/f'sky_{sky}.lib', gf_path, characterized_corners=True)
            pvt[key] = compact(run)
    checks['all_25_requested_core_corner_pairs_analyzed'] = len(pvt) == 25
    original = run_timing(case, output/'original_tt', args.sta, args.root/'pdk/sky130_tt_1v8.lib', args.root/'pdk/gf180_tt_1v8.lib')
    checks['SKY_JSON_TT_matches_original_Liberty'] = delta(original, pvt['tt_025C_1v80__tt_025C_1v80']) <= 1e-5

    def temperature_run(name, temperatures):
        model_dir = output/(name+'_models')
        model_dir.mkdir()
        models = {}
        for instance, (die, cell) in LANE_INSTANCES.items():
            path = model_dir/(instance+'.lib')
            if die == 'tx':
                models[instance] = sky_instance_model(root, cell, instance, temperatures[instance], path,
                                                      ('ff_n40C_1v65', 'ff_100C_1v65'))
            else:
                models[instance] = gf_instance_model(root, cell, instance, temperatures[instance], path)
        return run_timing(case, output/name, args.sta, root/'sky_ff_n40C_1v65.lib', root/'gf_core_ff_n40C_1v98.lib', instance_models=models)

    thermal = {}
    cold = temperature_run('endpoint_cold', {name: -40 for name in LANE_INSTANCES})
    hot = temperature_run('endpoint_hot', {name: 100 if die == 'tx' else 125 for name, (die, _) in LANE_INSTANCES.items()})
    checks['per_instance_cold_endpoint_equivalence'] = delta(cold, pvt['ff_n40C_1v65__ff_n40C_1v98']) <= 1e-5
    checks['per_instance_hot_endpoint_equivalence'] = delta(hot, pvt['ff_100C_1v65__ff_125C_1v98']) <= 1e-5
    temperatures = {name: 60 for name in LANE_INSTANCES}
    base = temperature_run('uniform_60C', temperatures)
    data = temperature_run('only_tx_data_100C', {**temperatures, 'tx_data': 100})
    clock = temperature_run('only_tx_clock_100C', {**temperatures, 'tx_clock': 100})
    receiver = temperature_run('only_rx_reg_100C', {**temperatures, 'rx_reg': 100})
    checks['data_temperature_changes_slack'] = delta(base, data) > 1e-5
    checks['clock_temperature_changes_slack'] = delta(base, clock) > 1e-5
    checks['receiver_temperature_changes_slack'] = delta(base, receiver) > 1e-5
    witnesses = {}
    for name, temperature, run in [('uniform_60C', 60, base), ('only_tx_data_100C', 100, data),
                                  ('only_tx_clock_100C', 60, clock)]:
        witness = delay_witness(root, output/name/'sta.log', temperature)
        witnesses[name] = witness
        checks[name+'_original_table_lookup_matches'] = all(witness[edge]['absolute_error_ns'] <= 2e-6 for edge in ('rise', 'fall'))
        checks[name+'_setup_arithmetic_matches'] = abs(witness['recomputed_setup_slack_ns']-run['setup_slack_ns']) <= 1e-5
    for key, run in [('cold', cold), ('hot', hot), ('uniform_60C', base), ('only_tx_data_100C', data),
                     ('only_tx_clock_100C', clock), ('only_rx_reg_100C', receiver)]:
        thermal[key] = compact(run)
    locations = json.loads(Path('examples/lane_instances.json').read_text())
    coupled = evaluate(case, output/'coupled', coupling_options=dict(sta=args.sta, model_root=root, locations=locations))
    thermal['coupled'] = compact(coupled['timing'])
    thermal['local_temperature_c'] = {name: model['temperature_c'] for name, model in coupled['timing']['instance_models'].items()}
    checks['distinct_local_temperatures'] = len(set(thermal['local_temperature_c'].values())) > 1
    checks['physical_signoff_not_claimed'] = not coupled['qualification']['complete_package_signoff']
    for name, corners, value in [('out_of_range', ('tt_025C_1v80', 'tt_100C_1v80'), 101),
                                  ('mixed_process_voltage', ('ff_n40C_1v65', 'tt_100C_1v80'), 60)]:
        try:
            sky_instance_model(root, 'buf_8', 'negative', value, output/(name+'.lib'), corners)
        except ValueError:
            checks[name+'_rejected'] = True
        else:
            checks[name+'_rejected'] = False
    pad = {'status': 'unexpectedly_accepted', 'valid_slack_ns': None}
    try:
        run_timing(case, output/'pad_3v3', args.sta, args.root/'pdk/sky130_tt_1v8.lib', root/'gf_core_tt_3v3.lib',
                   sky_pad_lib=root/'sky_io_tt_1v8_3v3.lib', gf_pad_lib=root/'gf_io_tt_3v3_assembled.lib')
    except ValueError as error:
        pad.update(status='rejected', reason=str(error))
    log = (output/'pad_3v3/sta.log').read_text()
    pad['violations'] = [line.strip() for line in log.split('Startpoint:', 1)[0].splitlines() if '(VIOLATED)' in line]
    checks['pad_slew_violation_detected'] = (pad['status'] == 'rejected' and
        'electrical design-rule violation' in pad.get('reason', '') and len(pad['violations']) == 2 and
        not re.search(r'Warning:|Error:', log))
    report = {'software_checks_passed': all(checks.values()), 'checks': checks,
              'physical_package_calibration': 'not_completed_no_measurements',
              'full_PVT_signoff': False, 'high_speed_PHY_qualification': False,
              'temperature_interpolation_holdout_validated': False,
              'source': source_revision(), 'assembly': assembly, 'pvt': pvt, 'temperature': thermal, 'pad': pad,
              'independent_delay_witnesses': witnesses,
              'rejected_expectation': {'data_and_clock_heating_always_have_opposite_setup_effect': False,
                  'reason': 'At this FF operating point, rising data delay decreases with temperature while falling clock delay increases. Source table queries and expanded paths, not a monotonic-temperature assumption, determine slack.',
                  'initial_failed_run': 'v03-validation-01'},
              'coverage_gaps': ['pad PVT combinations are incomplete',
                                'no independent temperature holdout SPICE characterization',
                                'GF180 TT temperature pair unavailable',
                                'different core voltage domains require a qualified I/O interface',
                                'no channel extraction, inductance, crosstalk, jitter, eye or BER validation',
                                'package resistance remains at reference temperature',
                                'no measured package stack, material or thermal/link data']}
    (output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'software_checks_passed': report['software_checks_passed'], 'checks': checks,
                      'pad': pad, 'local_temperature_c': thermal['local_temperature_c']}, indent=2))
    return 0 if report['software_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
