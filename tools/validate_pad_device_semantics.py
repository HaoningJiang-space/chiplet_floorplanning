"""DC controls for m/mult and the actual upstream metal-resistor edits."""

import argparse
import os
from pathlib import Path
import subprocess

import numpy as np

from validation.pad_sources import digest, prepare
from validation.pad_spice import log_diagnostics
from validation.sources import write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('local/pad-spice'))
    p.add_argument('--ngspice', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root, output, executable = args.root.resolve(), args.output.resolve(), args.ngspice.resolve()
    manifest = prepare(root)
    output.mkdir(parents=True, exist_ok=False)
    init = output / 'init'
    init.mkdir()
    (init / 'spinit').write_bytes(b'* Isolated initialization.\n')
    devices = []
    lines = ['DC semantics controls; not characterization',
             f'.lib "{root / "sky130A"}/libs.tech/ngspice/sky130.lib.spice" tt',
             'V33 v33 0 3.3', 'VG gate 0 1.0']
    for m, mult in ((1, 1), (1, 2), (2, 1), (2, 2)):
        name = f'm{m}_mult{mult}'
        devices.append(dict(name=name, kind='pfet', m=m, mult=mult))
        lines += [f'V{name} {name} 0 1.0',
                  f'X{name} {name} gate v33 v33 sky130_fd_pr__pfet_g5v0d10v5 m={m} mult={mult} w=1 l=0.6 sa=0.265 sb=0.265 sd=0.28']
    resistors = [('m1_unspecified', 'm1', ''), ('m1_unit', 'm1', 'L=1 W=1'),
                 ('m3_unit', 'm3', 'L=1 W=1'), ('m3_narrow', 'm3', 'L=0.035 W=1.07'),
                 ('m3_wide', 'm3', 'L=0.035 W=12.37'), ('m4_unit', 'm4', 'L=1 W=1'),
                 ('m4_wide', 'm4', 'L=0.035 W=12.35')]
    for name, model, dimensions in resistors:
        devices.append(dict(name=name, kind='resistor', model=model, dimensions=dimensions))
        lines += [f'V{name} {name} 0 1.0', f'R{name} {name} 0 sky130_fd_pr__res_generic_{model} {dimensions}']
    lines += ['.temp 25', '.options reltol=1e-5 abstol=1e-12 vntol=1e-7', '.control',
              'set numdgt=15', 'set wr_singlescale', 'set wr_vecnames', 'op',
              'wrdata currents.txt ' + ' '.join(f'i(v{d["name"]})' for d in devices), 'quit', '.endc', '.end']
    content = '\n'.join(lines) + '\n'
    (output / 'deck.sp').write_bytes(content.encode())
    frozen = dict(devices=devices, temperature_c=25, supply_v=3.3, gate_v=1.0, drain_or_resistor_voltage_v=1.0,
                  source_lock=manifest, ngspice_sha256=digest(executable.read_bytes()), deck_sha256=digest(content.encode()),
                  scope='isolated DC parameter-semantics observation at one bias; not timing or physical validation')
    write_json(output / 'frozen-inputs.json', frozen)
    run = subprocess.run([str(executable), '-n', '-D', 'ngbehavior=hsa', '-b', 'deck.sp'],
                         cwd=output, capture_output=True, text=True, timeout=120,
                         env={**os.environ, 'SPICE_SCRIPTS': str(init), 'OMP_NUM_THREADS': '1'})
    log = run.stdout + run.stderr
    (output / 'ngspice.log').write_bytes(log.encode())
    report = dict(frozen_inputs=frozen, returncode=run.returncode, diagnostics=log_diagnostics(log),
                  log_sha256=digest(log.encode()), software_checks_passed=False, physical_model_qualified=False)
    if run.returncode == 0 and (output / 'currents.txt').exists():
        values = np.loadtxt(output / 'currents.txt', skiprows=1).reshape(-1)
        if len(values) != len(devices) + 1 or not np.all(np.isfinite(values)):
            raise ValueError('invalid DC control samples')
        currents = {d['name']: float(v) for d, v in zip(devices, values[1:])}
        ratios = {name: currents[name] / currents['m1_mult1'] for name in ('m1_mult2', 'm2_mult1', 'm2_mult2')}
        report.update(currents_a=currents, pfet_current_ratios=ratios,
                      resistor_ohms={d['name']: -1.0 / currents[d['name']] for d in devices if d['kind'] == 'resistor'},
                      waveform_sha256=digest((output / 'currents.txt').read_bytes()),
                      software_checks_passed=all(abs(ratios[k] - v) < 1e-6 for k, v in
                                                 [('m1_mult2', 1.0), ('m2_mult1', 2.0), ('m2_mult2', 2.0)]))
    write_json(output / 'report.json', report)
    print({k: report.get(k) for k in ('software_checks_passed', 'pfet_current_ratios', 'resistor_ohms')})
    if not report['software_checks_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
