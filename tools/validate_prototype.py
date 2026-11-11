"""Low-speed real-pad prototype and geometry gates; no physical signoff."""

import argparse
import copy
import json
from pathlib import Path
import subprocess

from chiplet_floorplanning.characterization import run_coupled_timing
from chiplet_floorplanning.cli import source_revision
from chiplet_floorplanning.liberty_checks import check_pad_tables
from chiplet_floorplanning.model import load_case, parse_case
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.thermal import solve_steady
from chiplet_floorplanning.timing import parse_sta_log, run_timing
from chiplet_floorplanning.interconnect import estimate_links
from prepare_characterization import prepare


def compact(result):
    return {k: result[k] for k in ('setup_slack_ns', 'hold_slack_ns', 'timing_constraints_met')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('local'))
    parser.add_argument('--sta', type=Path, default=Path('local/upstream/OpenSTA/app/sta'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assembly = prepare(args.root)
    output, root = args.output, args.root/'pdk-v03'
    output.mkdir(parents=True, exist_ok=False)
    base = load_case('examples/low_speed_gpio.json')
    options = dict(sta=args.sta, sky_lib=args.root/'pdk/sky130_tt_1v8.lib', gf_lib=root/'gf_core_tt_3v3.lib',
                   sky_pad_lib=root/'sky_io_tt_1v8_3v3.lib', gf_pad_lib=root/'gf_bi_t_tt_3v3_assembled.lib',
                   pad_direction='gf180_to_sky130')
    checks, results, negative = {}, {}, {}
    nominal = run_timing(base, output/'nominal', **options)
    results['nominal'] = compact(nominal)
    checks['nominal_50MHz_setup_hold'] = nominal['timing_constraints_met']
    checks['all_16_active_pad_queries_in_domain'] = len(nominal['pad_table_checks']) == 16
    checks['eight_pad_arcs_in_expanded_paths_match'] = sum(r['used_in_reported_path'] for r in nominal['pad_table_checks']) == 8
    slower = run_timing(base, output/'period_40ns', period_ns=40, **options)
    results['period_40ns'] = compact(slower)
    checks['half_period_setup_hold_change'] = all(abs(slower[k]-nominal[k]-10) < 2e-5
                                                for k in ('setup_slack_ns', 'hold_slack_ns'))
    faster = run_timing(base, output/'period_2ns', period_ns=2, **options)
    results['period_2ns'] = compact(faster)
    checks['too_fast_negative_setup_preserved'] = faster['setup_slack_ns'] < 0 and not faster['timing_constraints_met']
    for length in (0.01, 0.1, 1.0, 6.0, 12.0):
        raw = copy.deepcopy(base.input_data)
        raw['chiplets'][1]['placement_mm']['x'] = 4+length
        raw['package_mm']['width'] = max(12, 8+length)
        for link in raw['links']:
            link['route_points_mm'][-1][0] = 4+length
        case = parse_case(raw)
        name = f'length_{length}_mm'
        try:
            result = run_timing(case, output/name, **options)
            results[name] = compact(result)
            checks[name] = length < 12 and result['timing_constraints_met']
        except ValueError as error:
            negative[name] = str(error)
            checks[name] = length == 12 and 'electrical design-rule violation' in str(error)
    # The original direction must remain a failing electrical control.
    try:
        run_timing(base, output/'original_direction', **{**options, 'pad_direction': 'sky130_to_gf180',
                   'gf_pad_lib': root/'gf_io_tt_3v3_assembled.lib'})
        checks['original_direction_rejected'] = False
    except ValueError as error:
        negative['original_direction'] = str(error)
        checks['original_direction_rejected'] = 'electrical design-rule violation' in str(error)

    # Real-library small buffer is legal logic but below the pad's load table.
    under = output/'underloaded_receiver'
    under.mkdir()
    for name in ('lane.v', 'wire_models.lib', 'package.spef', 'run.tcl'):
        content = (output/'nominal'/name).read_text()
        if name == 'lane.v':
            content = content.replace('sky130_fd_sc_hd__buf_16 rx_data', 'sky130_fd_sc_hd__buf_1 rx_data')
        (under/name).write_text(content)
    run = subprocess.run([str(args.sta.resolve()), '-exit', 'run.tcl'], cwd=under, capture_output=True, text=True, timeout=120)
    log = run.stdout+run.stderr
    (under/'sta.log').write_text(log)
    if run.returncode:
        raise ValueError('underload control did not execute')
    parse_sta_log(log, estimate_links(base))
    try:
        check_pad_tables(log, options['sky_pad_lib'], options['gf_pad_lib'])
        checks['underloaded_receiver_rejected'] = False
    except ValueError as error:
        negative['underloaded_receiver'] = str(error)
        checks['underloaded_receiver_rejected'] = 'outside characterized' in str(error)
        (under/'rejection.json').write_text(json.dumps({'status': 'rejected', 'reason': str(error)}, indent=2)+'\n')

    # Pad TT timing and experimental temperature-dependent core harness are
    # separate models. Never combine them into a claimed qualified hot link.
    locations = json.loads(Path('examples/lane_instances.json').read_text())
    meshes = {}
    for layout, shift in (('aligned', 0.0), ('moved', 0.137)):
        records = []
        for nx, ny in ((24, 16), (48, 32), (96, 64)):
            raw = copy.deepcopy(load_case('examples/layered_two_chiplets.json').input_data)
            raw['chiplets'][0]['placement_mm']['x'] += shift
            raw['grid'] = {'nx': nx, 'ny': ny, 'mode': 'geometry_conformal'}
            case = parse_case(raw)
            power, _ = rasterize(case)
            grid, thermal = solve_steady(case, power)
            run = run_coupled_timing(case, grid, output/f'{layout}_{nx}', args.sta, root, locations)
            records.append({'requested_nx': nx, 'actual_nx': case.nx, 'actual_ny': case.ny,
                            'peak_c': thermal['peak_c'], 'energy_balance_error_w': thermal['energy_balance_error_w'],
                            'instance_temperature_c': {k: v['temperature_c'] for k, v in run['instance_models'].items()},
                            **compact(run)})
        a, b = records[-2:]
        delta_t = max(abs(a['instance_temperature_c'][k]-b['instance_temperature_c'][k]) for k in a['instance_temperature_c'])
        delta_slack = max(abs(a[k]-b[k])*1e3 for k in ('setup_slack_ns', 'hold_slack_ns'))
        checks[layout+'_local_temperature_mesh_convergence'] = delta_t <= 0.1
        checks[layout+'_slack_mesh_convergence'] = delta_slack <= 1.0
        meshes[layout] = {'records': records, 'last_instance_temperature_change_k': delta_t,
                          'last_slack_change_ps': delta_slack}
    report = {'software_checks_passed': all(checks.values()), 'checks': checks, 'results': results,
              'negative_controls': negative, 'pad_table_checks': nominal['pad_table_checks'], 'meshes': meshes,
              'interface': nominal['interface'], 'assembly': assembly, 'source': source_revision(),
              'physical_package_calibration': False, 'complete_package_signoff': False,
              'coverage_gaps': ['no measured sample or extracted package channel',
                                'no transistor-level pad waveform comparison', 'no pad-temperature coupling or full pad PVT',
                                'no high-speed PHY, jitter, crosstalk or BER qualification',
                                'no complete serial_link protocol or gate-level functional simulation']}
    (output/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: report[k] for k in ('software_checks_passed', 'checks', 'results', 'negative_controls')}, indent=2))
    return 0 if report['software_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
