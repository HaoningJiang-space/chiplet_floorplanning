"""Replay an admitted complete 25 C fabric in Xyce, retaining model warnings."""
import argparse
import json
from pathlib import Path
import re
import shutil

import numpy as np

from audit_integrated_transistors import build_fabric
from compare_transistor_layouts import validate_decks
from summarize_integrated_transistors import summarize
from chiplet_floorplanning.characterization import digest
from validation.xyce_output import execute, record_observation
from validation.pad_spice import crossing_ns


def measure(wave, observed, nodes, step):
    if wave.ndim != 2 or wave.shape[1] != len(observed)+3 or not np.isfinite(wave).all():
        raise ValueError('invalid output columns')
    t = wave[:, 0]*1e9
    if t[0] != 0 or t[-1] < 59.999 or np.any(np.diff(t) <= 0):
        raise ValueError('incomplete or nonmonotonic waveform')
    columns = {node: i+1 for i, node in enumerate(observed)}
    def cross(node, start, rising=True):
        mask = (t >= start-.05) & (t <= start+5)
        return crossing_ns(t[mask], wave[mask, columns[node]], .9, rising)
    rows = []
    for g in range(2):
        for lane in range(4):
            suffix = f'{g}_{lane}'
            for edge, launch in (('rise', 21.), ('fall', 41.)):
                origin = cross('clk', launch)
                arrival = cross(nodes['rx_'+suffix+':D'], launch, edge == 'rise')-origin
                capture = cross(nodes[f'inv_{g}:Y'], launch+10)-origin
                previous = cross(nodes[f'inv_{g}:Y'], launch-10)-origin
                q = wave[:, columns[nodes['rx_'+suffix+':Q']]]
                stable = q[(t >= launch+14) & (t <= launch+15)]
                if not len(stable) or np.max(abs(stable-(1.8 if edge == 'rise' else 0))) > .018:
                    raise ValueError('failed receiver capture')
                mask = (t >= launch) & (t <= launch+15)
                event = crossing_ns(t[mask], q[mask], .9, edge == 'rise')-origin
                if event < capture:
                    raise ValueError('Q before capture edge')
                rows.append(dict(step_ps=step, lane=suffix, edge=edge,
                    receiver_clock_to_q_ns=event-capture,
                    setup_window_ns=capture-arrival, hold_window_ns=arrival-previous))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout-s', type=float, default=600)
    parser.add_argument('--reuse-run', type=Path)
    args = parser.parse_args()
    if not np.isfinite(args.timeout_s) or args.timeout_s <= 0:
        raise ValueError('positive finite timeout required')
    raw = json.loads((args.run/'report.json').read_text())
    validate_decks(args.run, args.reference, raw)
    baseline = summarize(args.run, args.reference)
    for filename, sha in raw['primitive_sources']['files'].items():
        if digest(Path('local/pad-spice')/filename) != sha:
            raise ValueError('changed primitive source')
    sta = json.loads((args.reference/'report.json').read_text())
    _, nodes = build_fabric((args.reference/'fabric.v').read_text(), sta, (args.reference/'package.spef').read_text())
    observed = list(dict.fromkeys(raw['observed_nodes']))
    exe = Path('local/xyce-7.10/portable/bin/Xyce.exe').resolve()
    args.output.mkdir(exist_ok=False)
    report = dict(complete=False, physical_qualified=False, temperature_c=25,
        scope='complete uniform-25C circuit cross-simulator windows; not slack or physical calibration',
        source_sha256=digest(__file__), executable_sha256=digest(exe),
        input_sha256=digest(args.run/'report.json'), sta_receipt_sha256=digest(args.reference/'report.json'),
        verified_primitive_file_count=len(raw['primitive_sources']['files']), observed_nodes=observed,
        cases=[], paths=[])
    prior = json.loads((args.reuse_run/'report.json').read_text()) if args.reuse_run else None
    if prior:
        for key in ('input_sha256', 'sta_receipt_sha256', 'executable_sha256', 'observed_nodes'):
            if prior[key] != report[key]:
                raise ValueError('reuse identity mismatch: '+key)
    for case in raw['cases']:
        step = case['step_ps']
        original = args.run/f'step_{step:g}ps'
        source = (original/'deck.sp').read_text()
        prefix, control = source.split('.control\n')
        prefix, n = re.subn(r'(?m)^\.options scale=1u reltol=1e-6 abstol=1e-13 vntol=1e-8$',
            '.options parser scale=1u\n.options nonlin reltol=1e-6 abstol=1e-13\n.options nonlin-tran reltol=1e-6 abstol=1e-13', prefix)
        if n != 1 or prefix.count('.temp 25\n') != 1 or f'tran {step}p 60n 0 {step}p' not in control:
            raise ValueError('unexpected controls')
        prefix = prefix.replace('.temp 25\n', '.options device temp=25\n')
        deck = prefix+f'.tran {step:g}p 60n 0 {step:g}p\n.print tran format=csv precision=16 '+ ' '.join(f'V({n})' for n in observed)+' I(VDD) I(VCLK)\n.end\n'
        folder = args.output/f'step_{step:g}ps'
        folder.mkdir()
        (folder/'deck.cir').write_text(deck)
        reusable = [c for c in prior['cases'] if c['step_ps'] == step and c.get('returncode') == 0] if prior else []
        if len(reusable) > 1:
            raise ValueError('duplicate reusable case')
        if reusable:
            saved = args.reuse_run/f'step_{step:g}ps'
            manifest = reusable[0]['artifacts_sha256']
            if set(manifest) != {'deck.cir', 'deck.cir.csv', 'xyce.log'}:
                raise ValueError('incomplete reuse manifest')
            for name, sha in manifest.items():
                if digest(saved/name) != sha:
                    raise ValueError('modified reuse artifact')
            if (saved/'deck.cir').read_text() != deck:
                raise ValueError('reuse circuit or controls changed')
            for name in ('deck.cir.csv', 'xyce.log'):
                shutil.copy2(saved/name, folder/name)
            execution = dict(status='completed', returncode=0)
        else:
            execution = execute(exe, folder, timeout_s=args.timeout_s)
        record = dict(step_ps=step, **execution,
            reused_report_sha256=digest(args.reuse_run/'report.json') if reusable else None)
        rows = record_observation(report, args.output/'report.json', folder, record,
            [*[f'V({n})' for n in observed], 'I(VDD)', 'I(VCLK)'],
            lambda wave: measure(wave, observed, nodes, step))
        for row in rows:
            ref = next(r for r in baseline['paths'] if all(r[k] == row[k] for k in ('step_ps', 'lane', 'edge')))
            row['xyce_minus_ngspice_ps'] = {k: (row[k]-ref[k])*1000 for k in
                ('setup_window_ns', 'hold_window_ns', 'receiver_clock_to_q_ns')}
        report['paths'].extend(rows)
        record['warning_count'] = len(record['warnings']['messages'])
        (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    coarse = {(r['lane'], r['edge']): r for r in report['paths'] if r['step_ps'] == 5}
    fine = [r for r in report['paths'] if r['step_ps'] == 2.5]
    report['max_abs_simulator_difference_ps'] = {k: max(abs(r['xyce_minus_ngspice_ps'][k]) for r in report['paths']) for k in fine[0]['xyce_minus_ngspice_ps']}
    report['max_step_window_change_ps'] = max(abs(r[k]-coarse[r['lane'], r['edge']][k])*1000 for r in fine for k in ('setup_window_ns', 'hold_window_ns'))
    report['complete'] = True
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('paths', 'observed_nodes', 'cases')}, indent=2))


if __name__ == '__main__':
    main()
