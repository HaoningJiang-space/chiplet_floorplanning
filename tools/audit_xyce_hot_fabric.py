"""Bind saved local temperatures and hot SPEF to the complete transistor fabric."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from audit_integrated_transistors import build_fabric
from compare_xyce_fabric import measure
from probe_core_local_temperature import prepare_models
from chiplet_floorplanning.characterization import digest
from validation.xyce_output import read_wave, execute, record_observation, warning_inventory
from validation.decision_evidence import verify_saved_sta_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout', type=Path)
    parser.add_argument('cold_run', type=Path)
    parser.add_argument('transistor_source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    parent = json.loads((args.layout/'report.json').read_text())
    cold = json.loads((args.cold_run/'report.json').read_text())
    raw = json.loads((args.transistor_source/'report.json').read_text())
    exe = Path('local/xyce-7.10/portable/bin/Xyce.exe').resolve()
    if not cold['complete'] or cold['executable_sha256'] != digest(exe) or cold['input_sha256'] != digest(args.transistor_source/'report.json'):
        raise ValueError('unmatched cold simulator/source identity')
    if digest(args.layout/'temperature.npz') != parent['temperature_sha256']:
        raise ValueError('changed thermal field')
    circuits, receipts = {}, {}
    for mode in ('reference', 'feedback'):
        folder = args.layout/mode
        sta = json.loads((folder/'report.json').read_text())
        verify_saved_sta_files(sta, folder)
        embedded = parent['timing'][mode]
        if any(embedded.get(k) != v for k, v in sta.items() if k not in ('models', 'rc')):
            raise ValueError('STA/evaluator binding mismatch')
        if embedded['model_assignments'] != {n: {k: v for k, v in m.items() if k != 'path'} for n, m in sta['models'].items()}:
            raise ValueError('model assignment binding mismatch')
        circuits[mode], nodes = build_fabric((folder/'fabric.v').read_text(), sta, (folder/'package.spef').read_text())
        receipts[mode] = sta
    if cold['sta_receipt_sha256'] != digest(args.layout/'reference/report.json'):
        raise ValueError('cold run belongs to another layout')
    temps = parent['local_temperature_c']
    if set(temps) != set(receipts['feedback']['models']) or any(not np.isfinite(t) or not 25 <= t <= 100 for t in temps.values()):
        raise ValueError('invalid complete local-temperature domain')
    for instance, model in receipts['feedback']['models'].items():
        if model['temperature_c'] != temps[instance] or model['voltage_v'] != 1.8 or model['process'] != 'tt':
            raise ValueError('inconsistent PVT mapping')
    a, b = circuits['reference'], circuits['feedback']
    unchanged = lambda lines: Counter(line if not line.startswith('R_') else ' '.join(line.split()[:3]) for line in lines)
    if unchanged(a) != unchanged(b):
        raise ValueError('temperature comparison changed topology, cells or capacitance')
    args.output.mkdir(exist_ok=False)
    models, transforms = prepare_models(args.output, args.transistor_source, raw)
    hot = [line+f' cell_temp_c={temps[line.split()[0][2:]]:.17g}' if line.startswith('X_') else line for line in b]
    report = dict(complete=False, physical_qualified=False,
        scope='fixed-power assumed-package local-temperature and RC feedback, not real Pad or characterized slack',
        source_sha256=digest(__file__), executable_sha256=digest(exe), transforms=transforms,
        layout_receipt_sha256=digest(args.layout/'report.json'), cold_receipt_sha256=digest(args.cold_run/'report.json'),
        thermal_field_sha256=parent['temperature_sha256'], feedback_sta_sha256=digest(args.layout/'feedback/report.json'),
        local_temperature_c=temps, peak_temperature_c=parent['thermal']['peak_c'], cases=[], paths=[])
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    for step in (5., 2.5):
        folder = args.output/f'step_{step:g}ps'
        folder.mkdir()
        prior = args.cold_run/f'step_{step:g}ps'
        cases = [c for c in cold['cases'] if c['step_ps'] == step and c.get('returncode') == 0]
        if len(cases) != 1:
            raise ValueError('missing/duplicate cold case')
        manifest = cases[0]['artifacts_sha256']
        if set(manifest) != {'deck.cir', 'deck.cir.csv', 'xyce.log'}:
            raise ValueError('incomplete cold artifacts')
        for name, sha in manifest.items():
            if digest(prior/name) != sha:
                raise ValueError('modified cold artifact')
        if warning_inventory((prior/'xyce.log').read_text())['unknown_messages']:
            raise ValueError('cold diagnostic admission failed; regenerate cold baseline')
        lines = (prior/'deck.cir').read_text().splitlines()
        physical = [line for line in lines if line.startswith(('X_', 'C_', 'R_'))]
        if Counter(physical) != Counter(a):
            raise ValueError('cold deck differs from verified fabric')
        actual_includes = [line for line in lines if line.startswith('.include ')]
        expected = [f'.include "{(args.transistor_source/(cell+".spice")).resolve().as_posix()}"' for cell in raw['cell_sources']]
        if Counter(actual_includes) != Counter(expected):
            raise ValueError('unmatched source cell includes')
        replaced = []
        for line in lines:
            if line in physical:
                continue
            if line.startswith('.lib '):
                line = f'.lib "{(models/"libs.tech/ngspice/sky130.lib.spice").resolve().as_posix()}" tt'
            elif line.startswith('.include '):
                name = Path(line.split('"')[1]).name
                line = f'.include "{(args.output/name).resolve().as_posix()}"'
            if line == '.end':
                replaced.extend(hot)
            replaced.append(line)
        (folder/'deck.cir').write_text('\n'.join(replaced)+'\n')
        execution = execute(exe, folder, timeout_s=1800)
        rows = record_observation(report, args.output/'report.json', folder,
            dict(step_ps=step, **execution),
            [*[f'V({n})' for n in cold['observed_nodes']], 'I(VDD)', 'I(VCLK)'],
            lambda wave: measure(wave, cold['observed_nodes'], nodes, step))
        cold_rows = measure(read_wave(prior/'deck.cir.csv', [*[f'V({n})' for n in cold['observed_nodes']], 'I(VDD)', 'I(VCLK)']), cold['observed_nodes'], nodes, step)
        for row in rows:
            reference = next(r for r in cold_rows if r['lane'] == row['lane'] and r['edge'] == row['edge'])
            row['feedback_change_ps'] = {k: (row[k]-reference[k])*1000 for k in ('setup_window_ns', 'hold_window_ns', 'receiver_clock_to_q_ns')}
            row['sta_feedback_change_ps'] = {}
            for kind in ('setup', 'hold'):
                key = row['lane']+'_'+kind+'_'+row['edge']
                values = [receipts[m]['paths'][key] for m in ('reference', 'feedback')]
                window = lambda p: p['capture_arrival_ns']-p['data_arrival_ns'] if kind == 'setup' else p['data_arrival_ns']-p['capture_arrival_ns']
                row['sta_feedback_change_ps'][kind+'_window_ns'] = (window(values[1])-window(values[0]))*1000
        report['paths'].extend(rows)
        (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    report['complete'] = True
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Completed two-step hot fabric; physical qualification remains false')


if __name__ == '__main__':
    main()
