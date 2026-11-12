"""Replay hot/cold waveforms and quantify differential timing-model agreement."""
import argparse
from collections import Counter
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from audit_integrated_transistors import build_fabric
from compare_xyce_fabric import measure
from chiplet_floorplanning.characterization import digest
from validation.xyce_output import read_wave, warning_inventory
from validation.decision_evidence import verify_saved_sta_files


def summarize(hot_root, cold_root, layout):
    args = SimpleNamespace(hot=hot_root, cold=cold_root, layout=layout)
    hot = json.loads((args.hot/'report.json').read_text())
    cold = json.loads((args.cold/'report.json').read_text())
    if not hot['complete'] or not cold['complete'] or hot['executable_sha256'] != cold['executable_sha256']:
        raise ValueError('incomplete or unmatched simulator runs')
    if hot['cold_receipt_sha256'] != digest(args.cold/'report.json') or hot['layout_receipt_sha256'] != digest(args.layout/'report.json'):
        raise ValueError('receipt binding mismatch')
    if hot['thermal_field_sha256'] != digest(args.layout/'temperature.npz'):
        raise ValueError('thermal field changed')
    results = []
    sta = {}
    for mode in ('reference', 'feedback'):
        folder = args.layout/mode
        sta[mode] = json.loads((folder/'report.json').read_text())
        verify_saved_sta_files(sta[mode], folder)
    for step in (5., 2.5):
        measured = {}
        for label, root, report, mode in (('hot', args.hot, hot, 'feedback'), ('cold', args.cold, cold, 'reference')):
            cases = [c for c in report['cases'] if c['step_ps'] == step and c.get('returncode') == 0]
            if len(cases) != 1 or set(cases[0]['artifacts_sha256']) != {'deck.cir', 'deck.cir.csv', 'xyce.log'}:
                raise ValueError('incomplete artifact domain')
            folder = root/f'step_{step:g}ps'
            for name, sha in cases[0]['artifacts_sha256'].items():
                if digest(folder/name) != sha:
                    raise ValueError('modified raw artifact')
            if warning_inventory((folder/'xyce.log').read_text())['unknown_messages']:
                raise ValueError('unknown or suppressed diagnostic in paired evidence')
            reference = args.layout/mode
            expected, nodes = build_fabric((reference/'fabric.v').read_text(), sta[mode], (reference/'package.spef').read_text())
            if label == 'hot':
                expected = [line+f' cell_temp_c={hot["local_temperature_c"][line.split()[0][2:]]:.17g}' if line.startswith('X_') else line for line in expected]
            lines = (folder/'deck.cir').read_text().splitlines()
            if Counter(l for l in lines if l.startswith(('X_', 'R_', 'C_'))) != Counter(expected):
                raise ValueError('actual circuit differs from temperature/RC assignment')
            if label == 'hot':
                libline, = [line for line in lines if line.startswith('.lib ')]
                modelroot = Path(libline.split('"')[1]).parents[2]
                for transform in hot['transforms']:
                    target = (args.hot if '/' not in transform['path'] else modelroot)/transform['path']
                    if digest(target) != transform['transformed_sha256']:
                        raise ValueError('transformed model changed')
            measured[label] = measure(read_wave(folder/'deck.cir.csv', [*[f'V({n})' for n in cold['observed_nodes']], 'I(VDD)', 'I(VCLK)']), cold['observed_nodes'], nodes, step)
        for h, c in zip(measured['hot'], measured['cold']):
            if (h['lane'], h['edge']) != (c['lane'], c['edge']):
                raise ValueError('path alignment mismatch')
            for kind in ('setup', 'hold'):
                metric = kind+'_window_ns'
                key = h['lane']+'_'+kind+'_'+h['edge']
                sign = 1 if kind == 'setup' else -1
                window = lambda mode: sign*(sta[mode]['paths'][key]['capture_arrival_ns']-sta[mode]['paths'][key]['data_arrival_ns'])
                delta = (h[metric]-c[metric])*1000
                sta_delta = (window('feedback')-window('reference'))*1000
                results.append(dict(step_ps=step, lane=h['lane'], edge=h['edge'], window=kind,
                    cold_window_ns=c[metric], hot_window_ns=h[metric], xyce_feedback_change_ps=delta,
                    sta_cold_window_ns=window('reference'), sta_hot_window_ns=window('feedback'),
                    sta_feedback_change_ps=sta_delta, model_change_difference_ps=delta-sta_delta,
                    opposite_change_direction=delta*sta_delta < 0))
    fine = [r for r in results if r['step_ps'] == 2.5]
    coarse = {(r['lane'], r['edge'], r['window']): r for r in results if r['step_ps'] == 5}
    summary = dict(complete=True, diagnostics_admitted=True, physical_qualified=False, source_sha256=digest(__file__),
        scope='one assumed-package layout; available windows, not physical slack or layout optimum',
        hot_receipt_sha256=digest(args.hot/'report.json'), cold_receipt_sha256=digest(args.cold/'report.json'),
        opposite_directions=sum(r['opposite_change_direction'] for r in fine),
        max_paired_step_change_ps=max(abs(r['xyce_feedback_change_ps']-coarse[r['lane'], r['edge'], r['window']]['xyce_feedback_change_ps']) for r in fine),
        max_abs_model_change_difference_ps=max(abs(r['model_change_difference_ps']) for r in fine),
        windows={}, paths=results)
    for kind in ('setup', 'hold'):
        rows = [r for r in fine if r['window'] == kind]
        summary['windows'][kind] = dict(cold_min_ns=min(r['cold_window_ns'] for r in rows),
            hot_min_ns=min(r['hot_window_ns'] for r in rows),
            feedback_change_range_ps=[min(r['xyce_feedback_change_ps'] for r in rows), max(r['xyce_feedback_change_ps'] for r in rows)])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hot', type=Path)
    parser.add_argument('cold', type=Path)
    parser.add_argument('layout', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(args.hot, args.cold, args.layout)
    args.output.write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'paths'}, indent=2))


if __name__ == '__main__':
    main()
