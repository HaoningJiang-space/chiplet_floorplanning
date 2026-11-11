"""Compare immutable TT models with measured HV primitive sweeps, locally."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np

from validation.measured_sources import verify, digest
from validation.measured_pad import read_mdm, deck, compare
from validation.pad_sources import prepare
from validation.sources import write_json, git_revision


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('results/physical-calibration'))
    ap.add_argument('--model-root', type=Path, default=Path('local/pad-spice'))
    ap.add_argument('--ngspice', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    source_lock = verify(args.root)
    models = prepare(args.model_root.resolve())
    args.output.mkdir(parents=True, exist_ok=False)
    init = args.output.resolve() / 'init'
    init.mkdir()
    (init / 'spinit').write_text('* Isolated initialization.\n')
    report = dict(scope='measured primitive versus TT conditional diagnostic; no fitting',
                  physical_model_qualified=False, measurement_temperature_c=None,
                  assumed_temperature_scenarios_c=[20, 25, 30], source_lock=source_lock,
                  model_lock=models, ngspice_sha256=digest(args.ngspice), git=git_revision(Path('.')),
                  plan_sha256=digest('docs/measured-calibration-plan.md'), cases=[],
                  missing=['measured temperature', 'lot identity', 'probe uncertainty',
                           'device layout/diffusion geometry', 'complete GPIO/PEX/package measurement'])
    for f in [Path(__file__), Path('tools/validation/measured_pad.py'), Path('docs/measured-calibration-plan.md')]:
        shutil.copyfile(f, args.output / f.name)
    write_json(args.output / 'frozen-inputs.json', report)
    for source in sorted((args.root / 'sources/sky-raw').rglob('*.mdm')):
        curves = read_mdm(source)
        device = source.parent.name
        for temperature in [20, 25, 30]:
            name = f'{device}-{source.stem.split("_")[-1].rstrip(")")}-{temperature}C'
            folder = args.output.resolve() / name
            folder.mkdir()
            content = deck(curves, args.model_root.resolve(), device, temperature)
            (folder / 'deck.sp').write_text(content)
            case = dict(name=name, device=device, assumed_temperature_c=temperature,
                        source=str(source), source_sha256=digest(source), deck_sha256=digest(folder / 'deck.sp'),
                        status='running', curves=[])
            report['cases'].append(case)
            write_json(args.output / 'progress.json', report)
            with (folder / 'ngspice.log').open('w') as log:
                try:
                    run = subprocess.run([str(args.ngspice.resolve()), '-n', '-D', 'ngbehavior=hsa', '-b', 'deck.sp'],
                                         cwd=folder, stdout=log, stderr=subprocess.STDOUT, timeout=120,
                                         env={**os.environ, 'SPICE_SCRIPTS': str(init), 'OMP_NUM_THREADS': '1'})
                    case.update(status='completed' if run.returncode == 0 else 'spice_failed', returncode=run.returncode)
                except subprocess.TimeoutExpired:
                    case['status'] = 'timeout'
            case['log_sha256'] = digest(folder / 'ngspice.log')
            if case['status'] == 'completed':
                for index, c in enumerate(curves):
                    file = folder / f'curve-{index:02d}.txt'
                    case['curves'].append(dict(index=index, sweep=c['sweep'], fixed_bias_v=c['fixed'],
                                               waveform_sha256=digest(file), **compare(c, np.loadtxt(file, skiprows=1))))
            write_json(args.output / 'progress.json', report)
            print(name, case['status'], len(case['curves']), flush=True)
    report['curve_comparisons'] = sum(len(c['curves']) for c in report['cases'])
    report['all_numerical_screens_passed'] = bool(report['curve_comparisons'] == 108 and all(
        c['model_kcl_screen'] and c['model_power_screen'] for batch in report['cases'] for c in batch['curves']))
    write_json(args.output / 'report.json', report)


if __name__ == '__main__':
    main()
