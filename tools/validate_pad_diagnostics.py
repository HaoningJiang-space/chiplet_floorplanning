"""Local nominal pad matrix and actual-STA operating-point diagnostics."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np

from chiplet_floorplanning.liberty_checks import active_arc, unique_group
from validate_pad_spice import definitions, simulate
from validation.pad_sources import prepare
from validation.pad_spice import differences
from validation.pad_diagnostics import (
    METRICS, finite_difference, measurement_convention, nominal_comparison,
    source_measurements, table_reference,
)
from validation.sources import git_revision, write_json

SLEWS_NS = (0.08, 0.18, 0.5)
LOADS_PF = (1.0, 2.0, 3.0, 4.0)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('local/pad-spice'))
    p.add_argument('--pdk-root', type=Path, default=Path('local/pdk-v03'))
    p.add_argument('--ngspice', type=Path, required=True)
    p.add_argument('--anchor', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root, output, executable = args.root.resolve(), args.output.resolve(), args.ngspice.resolve()
    sources = prepare(root)
    models = definitions(root, args.pdk_root.resolve())
    conventions = {side: measurement_convention(args.pdk_root / name) for side, name in (
        ('gf180', 'gf_io_tt_3v3.lib'), ('sky130', 'sky_io_tt_1v8_3v3.lib'))}
    arcs, limits, self_caps = {}, {}, {}
    for side, model in models.items():
        condition = '!IE&OE&PDRV0&PDRV1&!SL' if side == 'gf180' else '!IB_MODE_SEL&!VTRIP_SEL'
        arcs[side] = active_arc(model['library'], model['cell'], model['output'], condition)
        pin = unique_group(unique_group(Path(model['library']).read_text(), 'cell', model['cell']), 'pin', model['output'])
        match = re.search(r'\bmax_transition\s*:\s*([\d.]+)', pin)
        limits[side] = float(match[1]) if match else None
        self_caps[side] = float(re.search(r'\bcapacitance\s*:\s*([\d.]+)', pin)[1]) if side == 'gf180' else 0.0
    anchor = json.loads(args.anchor.read_text())
    if anchor['outcome'] != 'valid_timing_pass' or anchor['model_family'] != 'gpio':
        raise ValueError('anchor must be an admitted GPIO operating point')
    configs = []
    for slew in SLEWS_NS:
        for load in LOADS_PF:
            configs.append(dict(case_id=f'gf_s{slew:g}_c{load:g}', side='gf180',
                                input_slew_ns=slew, external_load_pf=load, role='matrix'))
    for instance, side in (('tx_data_pad', 'gf180'), ('rx_data_pad', 'sky130')):
        for edge in ('rise', 'fall'):
            selected = [r for r in anchor['pad_table_checks'] if
                        (r['instance'], r['mode'], r['edge']) == (instance, 'max', edge)]
            if len(selected) != 1 or not selected[0]['inside_source_table_domain'] or not selected[0]['bridge_paths']:
                raise ValueError('anchor arc missing or not used/in-domain')
            point = selected[0]
            if point['effective_load_pf'] <= self_caps[side]:
                raise ValueError('anchor external capacitance must be positive')
            configs.append(dict(case_id=side + '_anchor_' + edge, side=side,
                                input_slew_ns=point['input_slew_ns'],
                                external_load_pf=point['effective_load_pf'] - self_caps[side],
                                role='STA_anchor', selected_edge=edge, anchor_record=point))
    configs.append(dict(case_id='sky_nominal', side='sky130', input_slew_ns=1.0,
                        external_load_pf=0.022799, role='prior_nominal'))
    output.mkdir(parents=True, exist_ok=False)
    init = output / 'init'
    init.mkdir()
    (init / 'spinit').write_bytes(b'* Isolated initialization.\n')
    frozen = dict(configurations=configs, max_steps_ps=[5.0, 2.5], anchor_sha256=sha(args.anchor),
                  source=git_revision(Path.cwd()), source_lock=sources,
                  conventions=conventions, self_caps_pf=self_caps,
                  ngspice_sha256=sha(executable),
                  ngspice_version=subprocess.check_output([str(executable), '-n', '--version'], text=True),
                  source_files_sha256={name: sha(name) for name in (
                      'tools/validate_pad_diagnostics.py', 'tools/validate_pad_spice.py',
                      'tools/validation/pad_diagnostics.py', 'tools/validation/pad_spice.py',
                      'tools/validation/pad_sources.py', 'src/chiplet_floorplanning/liberty_checks.py')})
    write_json(output / 'frozen-inputs.json', frozen)

    def execute(item):
        config, step = item
        run_config = {k: config[k] for k in ('side', 'input_slew_ns', 'external_load_pf')}
        run_config.update(temperature_c=25, max_step_ps=step)
        record = simulate(run_config, models, root, executable, output, init)
        folder = output / record['name']
        record.update(case_id=config['case_id'], role=config['role'])
        record['file_hashes_match'] = (record['deck_sha256'] == sha(folder / 'deck.sp') and
                                       record['log_sha256'] == sha(folder / 'ngspice.log'))
        if record.get('waveform_gate_passed'):
            side = config['side']
            metrics = source_measurements(np.loadtxt(folder / 'waveform.txt', skiprows=1),
                                          conventions[side], 3.3, 3.3 if side == 'gf180' else 1.8)
            record['source_measurements'] = metrics
            record['definition_measurement_error_ns'] = max(abs(metrics[k] - record['metrics'][k]) for k in metrics)
            record['comparisons'] = {}
            for mapping in ('external_plus_self', 'external_only') if side == 'gf180' else ('external_only',):
                reference = table_reference(arcs[side], config['input_slew_ns'], config['external_load_pf'], self_caps[side], mapping)
                record['comparisons'][mapping] = nominal_comparison(metrics, reference, limits[side])
            if config['role'] == 'STA_anchor':
                edge = config['selected_edge']
                primary = record['comparisons']['external_plus_self' if side == 'gf180' else 'external_only']
                point = config['anchor_record']
                record['anchor_edge'] = edge
                record['anchor_table_error_ns'] = max(
                    abs(primary['metrics'][edge + '_delay_ns'] - point['delay_ns']),
                    abs(primary['metrics'][edge + '_slew_ns'] - point['table_output_slew_ns']))
        write_json(folder / 'diagnostic.json', record)
        return record

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(execute, [(c, step) for c in configs for step in (5.0, 2.5)]))
    usable = all(r.get('waveform_gate_passed', False) for r in records)
    cases, pairs = {}, []
    if usable:
        for config in configs:
            by_step = {r['max_step_ps']: r for r in records if r['case_id'] == config['case_id']}
            coarse, fine = by_step[5.0], by_step[2.5]
            convergence = differences(coarse['source_measurements'], fine['source_measurements'], 0.002, 0.005)
            cases[config['case_id']] = dict(config=config, fine=fine,
                convergence=convergence, step_changes_ns={m: abs(coarse['source_measurements'][m] - fine['source_measurements'][m]) for m in METRICS})
        edges = []
        for slew in SLEWS_NS:
            edges.extend((f'gf_s{slew:g}_c{a:g}', f'gf_s{slew:g}_c{b:g}', 'load') for a, b in zip(LOADS_PF, LOADS_PF[1:]))
        for load in LOADS_PF:
            edges.extend((f'gf_s{a:g}_c{load:g}', f'gf_s{b:g}_c{load:g}', 'input_slew') for a, b in zip(SLEWS_NS, SLEWS_NS[1:]))
        for first, second, variable in edges:
            a, b = cases[first], cases[second]
            pairs.append(dict(first=first, second=second, variable=variable, mappings={mapping: finite_difference(
                a['fine']['source_measurements'], b['fine']['source_measurements'],
                a['fine']['comparisons'][mapping], b['fine']['comparisons'][mapping],
                a['step_changes_ns'], b['step_changes_ns']) for mapping in ('external_plus_self', 'external_only')}))
    checks = dict(all_34_simulations_completed=len(records) == 34 and all(r['simulation_completed'] for r in records),
                  all_waveforms_valid=usable, byte_hash_receipts=all(r['file_hashes_match'] for r in records),
                  source_defined_measurement_agreement=usable and all(r['definition_measurement_error_ns'] < 1e-8 for r in records),
                  input_slews_match=usable and all(abs(r['source_measurements'][e + '_input_slew_ns'] - r['input_slew_ns']) < 1e-8 for r in records for e in ('rise', 'fall')),
                  all_17_halfstep_checks=len(cases) == 17 and all(c['convergence']['passed'] for c in cases.values()),
                  anchors_match_source_tables=usable and all(r.get('anchor_table_error_ns', 0) < 1e-5 for r in records),
                  all_17_pairs_recorded=len(pairs) == 17)
    report = dict(software_checks_passed=all(checks.values()), software_checks=checks,
                  frozen_inputs=frozen, models=models, records=records, cases=cases, finite_differences=pairs,
                  physical_model_qualified=False, hot_pad_timing_enabled=False,
                  scope='Nominal diagnostics of declared models; no physical error bound or complete D2D validation')
    write_json(output / 'report.json', report)
    print(json.dumps(checks, indent=2))
    return 0 if report['software_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
