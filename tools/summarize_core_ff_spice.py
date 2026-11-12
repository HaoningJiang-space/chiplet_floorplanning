"""Replay saved FF waveforms and compare fixed-stimulus diagnostic differences."""
import argparse
import hashlib
from itertools import product
import json
from pathlib import Path
import re

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from audit_core_ff_spice import measure
from chiplet_floorplanning.characterization import digest, interpolate_cell
from validation.pad_spice import crossing_ns


def summarize(root):
    report = json.loads((root/'report.json').read_text())
    stimulus = report['declared_stimulus']
    if stimulus != dict(supply_v=1.8, clock_and_data_slew_ns=.122474,
            external_loads_pf=[.00900162, .0235923], steps_ps=[2., 1.],
            data_advance_ns=[2., 3.], temperatures_c=[25., 62.5, 100.], thresholds_pct=[20, 50, 80]):
        raise ValueError('unexpected fixed stimulus declaration')
    expected = set(product([25., 62.5, 100.], stimulus['external_loads_pf'], [2., 3.], [2., 1.]))
    cases = report['cases']
    key = lambda c: (c['temp_c'], c['external_load_pf'], c['data_advance_ns'], c['step_ps'])
    if not report['complete'] or len(cases) != len(expected) or set(map(key, cases)) != expected:
        raise ValueError('incomplete fixed stimulus domain')
    if digest(root/'dfxtp_1.spice') != report['netlist_sha256']:
        raise ValueError('changed netlist')
    for path, expected_hash in report['library_source_sha256'].items():
        if digest(path) != expected_hash:
            raise ValueError('changed reference library')
    endpoints = [json.loads(Path(f'local/pdk-v03/sky_dfxtp_1_tt_{t:03d}C_1v80.json').read_text()) for t in (25, 100)]
    for case in cases:
        folder = root/case['name']
        if set(case['artifacts_sha256']) != {'deck.sp', 'wave.txt', 'ngspice.log'}:
            raise ValueError('incomplete artifacts')
        for name, sha in case['artifacts_sha256'].items():
            if digest(folder/name) != sha:
                raise ValueError('changed saved artifact')
        deck = (folder/'deck.sp').read_text()
        for pattern, value in ((r'(?m)^\.temp (\S+)$', case['temp_c']),
                               (r'(?m)^Cload q 0 (\S+)p$', case['external_load_pf']),
                               (r'(?m)^tran (\S+)p 18n 0 \S+p$', case['step_ps'])):
            matched = re.search(pattern, deck)
            if not matched or float(matched[1]) != value:
                raise ValueError('deck condition differs from recorded case')
        data = np.loadtxt(folder/'wave.txt')
        observed = measure(data)
        times = data[:, 0]*1e9
        for edge, start in (('rise', 7.), ('fall', 13.)):
            rising = edge == 'rise'
            mask = (times > start-case['data_advance_ns']-.1) & (times < start-.1)
            t, voltage = times[mask], data[mask, 2]
            actual_slew = abs(crossing_ns(t, voltage, 1.44, rising)-crossing_ns(t, voltage, .36, rising))
            data_mid = crossing_ns(t, voltage, .9, rising)
            clock_mid = start+stimulus['clock_and_data_slew_ns']/.6/2
            if abs(actual_slew-stimulus['clock_and_data_slew_ns']) > 1e-8 or abs(clock_mid-data_mid-case['data_advance_ns']) > 1e-8:
                raise ValueError('data stimulus differs from fixed declaration')
        for metric, values in case['metrics'].items():
            if abs(observed[metric+'_ns']-values['spice_ns']) > 1e-12:
                raise ValueError('saved metric differs from waveform')
            edge, quantity = metric.split('_')
            tables = interpolate_cell(*endpoints, (case['temp_c']-25)/75)['pin,Q']['timing']
            name = 'cell_'+edge if quantity == 'delay' else edge+'_transition'
            table = tables[name+',del_1_7_7']
            prediction = float(RegularGridInterpolator((table['index_1'], table['index_2']),
                table['values'], bounds_error=True)([[stimulus['clock_and_data_slew_ns'], case['external_load_pf']]])[0])
            if abs(prediction-values['liberty_ns']) > 1e-12 or abs((observed[metric+'_ns']-prediction)*1000-values['difference_ps']) > 1e-9:
                raise ValueError('saved Liberty comparison differs from recomputation')
    indexed = {key(c): c for c in cases}
    metrics = ('rise_delay', 'fall_delay', 'rise_slew', 'fall_slew')
    step_changes, advance_changes, thermal = [], [], []
    for temp, load, advance in product([25., 62.5, 100.], stimulus['external_loads_pf'], [2., 3.]):
        for metric in metrics:
            a = indexed[temp, load, advance, 2.]['metrics'][metric]['spice_ns']
            b = indexed[temp, load, advance, 1.]['metrics'][metric]['spice_ns']
            step_changes.append(abs(a-b)*1000)
    for temp, load, step in product([25., 62.5, 100.], stimulus['external_loads_pf'], [2., 1.]):
        for metric in metrics:
            a = indexed[temp, load, 2., step]['metrics'][metric]['spice_ns']
            b = indexed[temp, load, 3., step]['metrics'][metric]['spice_ns']
            advance_changes.append(abs(a-b)*1000)
    for load, metric in product(stimulus['external_loads_pf'], metrics):
        records = [indexed[temp, load, 2., 1.]['metrics'][metric] for temp in (25., 62.5, 100.)]
        cold, middle, hot = records
        spice_delta = hot['spice_ns']-cold['spice_ns']
        liberty_delta = hot['liberty_ns']-cold['liberty_ns']
        thermal.append(dict(external_load_pf=load, metric=metric,
            spice_delta_ps=1000*spice_delta, liberty_delta_ps=1000*liberty_delta,
            delta_difference_ps=1000*(spice_delta-liberty_delta),
            midpoint_curvature_ps=1000*(middle['spice_ns']-(cold['spice_ns']+hot['spice_ns'])/2)))
    return dict(scope='Diagnostic only; no setup/hold or physical qualification', physical_qualified=False,
        raw_report_sha256=digest(root/'report.json'), raw_directory=str(root),
        replayed_waveforms=len(cases), max_step_change_ps=max(step_changes),
        max_data_advance_change_ps=max(advance_changes), temperature_comparisons=thermal,
        absolute_difference_range_ps=[min(v['difference_ps'] for c in cases for v in c['metrics'].values()),
                                      max(v['difference_ps'] for c in cases for v in c['metrics'].values())],
        experiment={k: v for k, v in report.items() if k != 'primitive_sources'},
        primitive_manifest_sha256=hashlib.sha256(json.dumps(report['primitive_sources'], sort_keys=True).encode()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.run)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'experiment'}, indent=2))
