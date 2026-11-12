"""Paired layout effects in complete-fabric SPICE and STA available windows."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

from audit_integrated_transistors import build_fabric
from summarize_integrated_transistors import summarize
from chiplet_floorplanning.characterization import digest


def validate_decks(run, reference, report):
    sta = json.loads((reference/'report.json').read_text())
    elements, _ = build_fabric((reference/'fabric.v').read_text(), sta, (reference/'package.spef').read_text())
    controls = []
    for case in report['cases']:
        folder = run/f'step_{case["step_ps"]:g}ps'
        lines = (folder/'deck.sp').read_text().splitlines()
        circuit = [line for line in lines if line.startswith(('X_', 'C_', 'R_'))]
        if Counter(circuit) != Counter(elements):
            raise ValueError('actual transistor deck differs from verified RC/cell fabric')
        observed = 'wrdata wave.txt '+' '.join(f'v({n})' for n in report['observed_nodes'])+' i(VDD) i(VCLK)'
        if lines.count(observed) != 1:
            raise ValueError('waveform column request differs from recorded columns')
        included = [line for line in lines if line.startswith('.include ')]
        expected_includes = []
        for cell, (_, sha) in report['cell_sources'].items():
            path = run/(cell+'.spice')
            if digest(path) != sha:
                raise ValueError('cell netlist differs from recorded source')
            expected_includes.append(f'.include "{path.resolve().as_posix()}"')
        if Counter(included) != Counter(expected_includes):
            raise ValueError('unexpected included cell netlist')
        # Explicitly allow only circuit/observation/path changes. Stimuli, output
        # loads, supply, temperature, solver options and integration stay identical.
        controls.append([line for line in lines if line not in circuit+included and not line.startswith('wrdata ')])
    return controls


def compare_rows(a, b):
    for row in a+b:
        if any(not math.isfinite(row[kind+suffix]) for kind in ('setup', 'hold')
               for suffix in ('_window_ns', '_window_difference_ps')):
            raise ValueError('finite window observations required')
    index = lambda rows: {(r['step_ps'], r['lane'], r['edge']): r for r in rows}
    ia, ib = index(a), index(b)
    expected = {(step, f'{g}_{lane}', edge) for step in (5., 2.5)
                for g in range(2) for lane in range(4) for edge in ('rise', 'fall')}
    if len(a) != len(expected) or len(b) != len(expected) or set(ia) != expected or set(ib) != expected:
        raise ValueError('complete paired path domain required')
    result = []
    for (_, lane, edge) in sorted(key for key in expected if key[0] == 2.5):
        for kind in ('setup', 'hold'):
            values = {}
            for step in (5., 2.5):
                x, y = ia[step, lane, edge], ib[step, lane, edge]
                delta_spice = (y[kind+'_window_ns']-x[kind+'_window_ns'])*1000
                delta_bias = y[kind+'_window_difference_ps']-x[kind+'_window_difference_ps']
                values[step] = (delta_spice, delta_spice-delta_bias)
            spice, sta = values[2.5]
            result.append(dict(lane=lane, edge=edge, window=kind, spice_b_minus_a_ps=spice,
                sta_b_minus_a_ps=sta, differential_model_discrepancy_ps=spice-sta,
                paired_step_change_ps=spice-values[5.][0],
                opposite_ordering=(spice*sta < 0)))
    minima = {}
    for kind in ('setup', 'hold'):
        minima[kind] = {}
        for label, rows in (('a', a), ('b', b)):
            fine = [r for r in rows if r['step_ps'] == 2.5]
            spice = min(r[kind+'_window_ns'] for r in fine)
            sta = min(r[kind+'_window_ns']-r[kind+'_window_difference_ps']/1000 for r in fine)
            minima[kind][label] = dict(spice_minimum_ns=spice, sta_minimum_ns=sta)
        x, y = minima[kind]['a'], minima[kind]['b']
        ds = (y['spice_minimum_ns']-x['spice_minimum_ns'])*1000
        dt = (y['sta_minimum_ns']-x['sta_minimum_ns'])*1000
        minima[kind].update(spice_b_minus_a_ps=ds, sta_b_minus_a_ps=dt, opposite_ordering=ds*dt < 0)
    return dict(paths=result, worst_window_comparison=minima,
        opposite_path_orderings=sum(r['opposite_ordering'] for r in result),
        max_abs_paired_step_change_ps=max(abs(r['paired_step_change_ps']) for r in result),
        max_abs_differential_model_discrepancy_ps=max(abs(r['differential_model_discrepancy_ps']) for r in result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('a_run', 'a_reference', 'b_run', 'b_reference'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = [json.loads((p/'report.json').read_text()) for p in (args.a_run, args.b_run)]
    for key in ('primitive_sources', 'cell_sources', 'executable_sha256'):
        if raw[0][key] != raw[1][key]:
            raise ValueError('different physical source/runtime identity: '+key)
    controls = [validate_decks(run, ref, record) for run, ref, record in
                zip((args.a_run, args.b_run), (args.a_reference, args.b_reference), raw)]
    if controls[0] != controls[1]:
        raise ValueError('different stimuli, solver controls or non-route loads')
    summaries = [summarize(run, ref) for run, ref in
                 ((args.a_run, args.a_reference), (args.b_run, args.b_reference))]
    result = compare_rows(summaries[0]['paths'], summaries[1]['paths'])
    result.update(source_sha256=digest(__file__), complete=True, physical_qualified=False,
        scope='paired 25 C core-fabric available windows, not physical timing feasibility or a model-error bound',
        uncertainty_status='uncertainty_unquantified', equal_stimuli_and_model_identity=True,
        inputs={label: dict(run=str(run), reference=str(ref), raw_report_sha256=digest(run/'report.json'),
            sta_receipt_sha256=digest(ref/'report.json'), placed_sha256=digest(ref.parent/'placed.json'),
            evaluator_receipt_sha256=digest(ref.parent/'report.json'),
            thermal_peak_c=json.loads((ref.parent/'report.json').read_text())['thermal']['peak_c'])
            for label, run, ref in (('a', args.a_run, args.a_reference), ('b', args.b_run, args.b_reference))})
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'paths'}, indent=2))


if __name__ == '__main__':
    main()
