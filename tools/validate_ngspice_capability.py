"""Isolate behavioral-capacitor/multiplier execution without any PDK assets."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess

from validation.sources import write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    init = args.output.resolve() / 'init'
    init.mkdir()
    (init / 'spinit').write_bytes(b'* Isolated initialization.\n')
    records = []
    for label, executable in (('baseline', args.baseline), ('candidate', args.candidate)):
        executable = executable.resolve()
        for behavioral in (False, True):
            for multiplier in (1, 4):
                folder = args.output / f'{label}_behavioral{int(behavioral)}_m{multiplier}'
                folder.mkdir()
                capacitor = "C1 a b c='1p*(1+0.1*tanh(v(a,b)))'" if behavioral else 'C1 a b 1p'
                content = f'''Synthetic capacitor execution control, no PDK
V1 in 0 PULSE(0 1 1n 100p 100p 1n 3n)
R1 in out 100
X1 out 0 cap m={multiplier}
.subckt cap a b
{capacitor}
.ends cap
.control
tran 10p 6n
quit
.endc
.end
'''
                (folder / 'deck.sp').write_bytes(content.encode())
                run = subprocess.run([str(executable), '-n', '-b', 'deck.sp'], cwd=folder,
                                     text=True, capture_output=True, timeout=30,
                                     env={**os.environ, 'SPICE_SCRIPTS': str(init), 'OMP_NUM_THREADS': '1'})
                log = run.stdout + run.stderr
                (folder / 'ngspice.log').write_bytes(log.encode())
                records.append(dict(tool=label, executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                                    behavioral=behavioral, multiplier=multiplier,
                                    returncode=run.returncode,
                                    completed=run.returncode == 0 and 'No. of Data Rows' in log,
                                    deck_sha256=hashlib.sha256(content.encode()).hexdigest(),
                                    log_sha256=hashlib.sha256(log.encode()).hexdigest(),
                                    diagnostics=[line for line in log.splitlines() if 'Error' in line or 'unknown parameter' in line]))
    write_json(args.output / 'report.json', dict(records=records,
               scope='Synthetic execution probe, not a pad waveform or physical-model validation'))
    for record in records:
        print(record['tool'], record['behavioral'], record['multiplier'], record['completed'])


if __name__ == '__main__':
    main()
