"""Re-read full-fabric waveforms; distinguish available windows from slack."""
import argparse
import json
from pathlib import Path

import numpy as np

from audit_integrated_transistors import build_fabric
from chiplet_floorplanning.characterization import digest
from validation.decision_evidence import verify_saved_sta_files
from validation.pad_spice import crossing_ns


def summarize(root, reference):
    report = json.loads((root/'report.json').read_text())
    sta = json.loads((reference/'report.json').read_text())
    verify_saved_sta_files(sta, reference)
    if digest(reference/'report.json') != report['reference_receipt_sha256']:
        raise ValueError('different STA reference')
    if not report['complete'] or [c['step_ps'] for c in report['cases']] != [5., 2.5]:
        raise ValueError('incomplete time-step experiment')
    _, nodes = build_fabric((reference/'fabric.v').read_text(), sta, (reference/'package.spef').read_text())
    columns = {node: i+1 for i, node in enumerate(report['observed_nodes'])}
    records = []
    for case in report['cases']:
        folder = root/f'step_{case["step_ps"]:g}ps'
        if set(case['artifacts_sha256']) != {'deck.sp', 'wave.txt', 'ngspice.log'}:
            raise ValueError('incomplete artifact manifest')
        for name, sha in case['artifacts_sha256'].items():
            if digest(folder/name) != sha:
                raise ValueError('modified simulation artifact')
        wave = np.loadtxt(folder/'wave.txt')
        t = wave[:, 0]*1e9
        if not np.isfinite(wave).all() or np.any(np.diff(t) <= 0) or t[-1] < 59.999:
            raise ValueError('invalid waveform')
        def cross(node, start, rising=True):
            mask = (t >= start-.05) & (t <= start+5)
            return crossing_ns(t[mask], wave[mask, columns[node]], .9, rising)
        for group in range(2):
            for lane in range(4):
                suffix = f'{group}_{lane}'
                for edge, launch in (('rise', 21.), ('fall', 41.)):
                    origin = cross('clk', launch)
                    arrival = cross(nodes['rx_'+suffix+':D'], launch, edge == 'rise')-origin
                    capture = cross(nodes[f'inv_{group}:Y'], launch+10)-origin
                    previous_capture = cross(nodes[f'inv_{group}:Y'], launch-10)-origin
                    qmask = (t >= launch+14) & (t <= launch+15)
                    if np.max(abs(wave[qmask, columns[nodes['rx_'+suffix+':Q']]]-(1.8 if edge == 'rise' else 0))) > .018:
                        raise ValueError('capture replay failed')
                    event_mask = (t >= launch) & (t <= launch+15)
                    q_time = crossing_ns(t[event_mask], wave[event_mask, columns[nodes['rx_'+suffix+':Q']]], .9, edge == 'rise')-origin
                    if q_time < capture:
                        raise ValueError('receiver Q transitioned before its capture edge')
                    setup = sta['paths'][suffix+'_setup_'+edge]
                    hold = sta['paths'][suffix+'_hold_'+edge]
                    setup_window = capture-arrival
                    hold_window = arrival-previous_capture
                    records.append(dict(step_ps=case['step_ps'], lane=suffix, edge=edge,
                        receiver_clock_to_q_ns=q_time-capture,
                        setup_window_ns=setup_window, hold_window_ns=hold_window,
                        setup_window_difference_ps=(setup_window-(setup['capture_arrival_ns']-setup['data_arrival_ns']))*1000,
                        hold_window_difference_ps=(hold_window-(hold['data_arrival_ns']-hold['capture_arrival_ns']))*1000))
    coarse = {(r['lane'], r['edge']): r for r in records if r['step_ps'] == 5}
    fine = [r for r in records if r['step_ps'] == 2.5]
    numerical = max(abs(r[k]-coarse[r['lane'], r['edge']][k])*1000
                    for r in fine for k in ('setup_window_ns', 'hold_window_ns'))
    return dict(physical_qualified=False, summary_source_sha256=digest(__file__),
        rc_matches_saved_spef=True, receiver_capture_edges_checked=True,
        raw_report_sha256=digest(root/'report.json'),
        scope='available data/capture windows, not characterized setup/hold slack or uncertainty bounds',
        replayed_paths=len(records), max_step_window_change_ps=numerical,
        minimum_setup_window_ns=min(r['setup_window_ns'] for r in fine),
        minimum_hold_window_ns=min(r['hold_window_ns'] for r in fine),
        setup_window_difference_range_ps=[min(r['setup_window_difference_ps'] for r in fine), max(r['setup_window_difference_ps'] for r in fine)],
        hold_window_difference_range_ps=[min(r['hold_window_difference_ps'] for r in fine), max(r['hold_window_difference_ps'] for r in fine)],
        paths=records, experiment={k: v for k, v in report.items() if k != 'primitive_sources'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.run, args.reference)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('paths', 'experiment')}, indent=2))
