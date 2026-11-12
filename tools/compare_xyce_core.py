"""Replay fixed inverter/buffer stimuli in Xyce; explicit cross-model diagnostic."""
import argparse
import itertools
import json
from pathlib import Path
import re
import subprocess

import numpy as np

from chiplet_floorplanning.characterization import digest
from validation.xyce_output import read_wave
from validation.pad_spice import crossing_ns


def measure(wave, cell, slew):
    if wave.ndim != 2 or wave.shape[1] != 5 or not np.isfinite(wave).all():
        raise ValueError('invalid waveform')
    t = wave[:, 0]*1e9
    if t[0] != 0 or t[-1] < 9.999 or np.any(np.diff(t) <= 0):
        raise ValueError('incomplete/nonmonotonic waveform')
    result = {}
    for rising, lo, hi in ((True, 1.9, 5.9), (False, 5.9, 9.9)):
        mask = (t >= lo) & (t <= hi)
        times, vin, output = t[mask], wave[mask, 1], wave[mask, 2]
        actual = abs(crossing_ns(times, vin, .36, rising)-crossing_ns(times, vin, 1.44, rising))
        if abs(actual-slew) > 1e-8:
            raise ValueError('input slew mismatch')
        out_rising = rising if cell == 'buf_8' else not rising
        edge = 'rise' if out_rising else 'fall'
        result[edge+'_delay'] = crossing_ns(times, output, .9, out_rising)-crossing_ns(times, vin, .9, rising)
        result[edge+'_slew'] = abs(crossing_ns(times, output, .36, out_rising)-crossing_ns(times, output, 1.44, out_rising))
        stable = output[times > hi-.2]
        if not len(stable) or np.max(abs(stable-(1.8 if out_rising else 0))) > .018:
            raise ValueError('output did not settle')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ref = json.loads((args.reference/'report.json').read_text())
    cell = ref['cell']
    if not ref['complete'] or cell not in ('inv_1', 'buf_8') or ref['restore_stress_geometry']:
        raise ValueError('unsupported reference')
    for filename, expected in ref['primitive_sources']['files'].items():
        if digest(Path('local/pad-spice')/filename) != expected:
            raise ValueError('primitive manifest changed: '+filename)
    if digest(args.reference/(cell+'.spice')) != ref['netlist_sha256']:
        raise ValueError('cell changed')
    stimuli = ref['declared_stimulus']
    expected = set(itertools.product((25., 62.5, 100.), stimuli['external_loads_pf'], stimuli['steps_ps']))
    keys = [(r['temp_c'], r['external_load_pf'], r['step_ps']) for r in ref['cases']]
    if len(set(keys)) != len(keys) or set(keys) != expected:
        raise ValueError('incomplete/duplicate reference domain')
    args.output.mkdir(exist_ok=False)
    exe = Path('local/xyce-7.10/portable/bin/Xyce.exe').resolve()
    report = dict(complete=False, physical_qualified=False, cell=cell,
        scope='uniform-temperature cross-simulator diagnostic; model substitutions retained, not hot-layout validation',
        source_sha256=digest(__file__), reference_sha256=digest(args.reference/'report.json'),
        executable_sha256=digest(exe), primitive_sources=ref['primitive_sources'],
        cell_sha256=ref['netlist_sha256'], cases=[])
    for row in ref['cases']:
        original = args.reference/row['name']
        for name, key in (('deck.sp', 'deck_sha256'), ('wave.txt', 'waveform_sha256')):
            if digest(original/name) != row[key]:
                raise ValueError('reference artifact changed')
        reference = measure(np.loadtxt(original/'wave.txt'), cell, row['input_slew_ns'])
        if any(abs(v-row['metrics'][k]['spice_ns']) > 1e-10 for k, v in reference.items()):
            raise ValueError('reference measurement mismatch')
        text = '\n'.join(line.strip() for line in (original/'deck.sp').read_text().splitlines())
        prefix, control = text.split('.control\n')
        # Preserve the entire physical circuit and stimuli; translate solver dialect only.
        prefix, count = re.subn(r'(?m)^\.options scale=1u reltol=1e-6 abstol=1e-13 vntol=1e-8$',
            '.options parser scale=1u\n.options nonlin reltol=1e-6 abstol=1e-13\n.options nonlin-tran reltol=1e-6 abstol=1e-13', prefix)
        if count != 1:
            raise ValueError('unexpected solver options')
        prefix, count = re.subn(r'(?m)^\.temp ([-+0-9.]+)$', r'.options device temp=\1', prefix)
        if count != 1 or f'tran {row["step_ps"]}p 10n 0 {row["step_ps"]}p' not in control:
            raise ValueError('unexpected reference temperature/transient controls')
        deck = prefix+f'.tran {row["step_ps"]}p 10n 0 {row["step_ps"]}p\n.print tran format=csv precision=16 V(vin) V(out) I(VDD) I(VIN)\n.end\n'
        folder = args.output/row['name']
        folder.mkdir()
        (folder/'deck.cir').write_text(deck)
        run = subprocess.run([str(exe), 'deck.cir'], cwd=folder, capture_output=True, text=True, timeout=60)
        log = run.stdout+run.stderr
        (folder/'log.txt').write_text(log)
        if run.returncode or re.search(r'(?i)netlist error|simulation aborted', log):
            raise ValueError('Xyce failed; retained raw log at '+str(folder))
        wave = read_wave(folder/'deck.cir.csv', ['V(vin)', 'V(out)', 'I(VDD)', 'I(VIN)'])
        metrics = measure(wave, cell, row['input_slew_ns'])
        report['cases'].append(dict(name=row['name'], temp_c=row['temp_c'], load_pf=row['external_load_pf'], step_ps=row['step_ps'],
            xyce_ns=metrics, ngspice_ns=reference, difference_ps={k: (metrics[k]-reference[k])*1000 for k in metrics},
            warning_count=len(re.findall(r'(?i)netlist warning', log)),
            version_substitution='oldest version supported' in log,
            deck_sha256=digest(folder/'deck.cir'), log_sha256=digest(folder/'log.txt'),
            waveform_sha256=digest(folder/'deck.cir.csv')))
        (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    report['temperature_differences'] = []
    for load, step in itertools.product(stimuli['external_loads_pf'], stimuli['steps_ps']):
        rows = {r['temp_c']: r for r in report['cases'] if r['load_pf'] == load and r['step_ps'] == step}
        for metric in rows[25.]['xyce_ns']:
            a = (rows[100.]['xyce_ns'][metric]-rows[25.]['xyce_ns'][metric])*1000
            b = (rows[100.]['ngspice_ns'][metric]-rows[25.]['ngspice_ns'][metric])*1000
            report['temperature_differences'].append(dict(load_pf=load, step_ps=step, metric=metric,
                xyce_25_100_ps=a, ngspice_25_100_ps=b, difference_ps=a-b))
    report['complete'] = True
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Completed', len(report['cases']), 'cases; physical qualification remains false')


if __name__ == '__main__':
    main()
