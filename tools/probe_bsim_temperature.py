"""Test local BSIM4 temperature syntax; manufactured device, not PDK validation."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from chiplet_floorplanning.characterization import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ngspice', type=Path, default=Path('local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe'))
    args = parser.parse_args()
    root = args.output
    root.mkdir(exist_ok=False)
    init = root/'empty-init'
    init.mkdir()
    (init/'spinit').write_text('* empty\n')
    report = dict(complete=False, source_sha256=digest(__file__), executable_sha256=digest(args.ngspice),
                  physical_calibration=False, scope='manufactured BSIM4 parameter support, not a SKY130 calibration', cases=[])
    declarations = [('global25', '', '', 25), ('global100', '', '', 100),
                    ('instance_temp', 'temp=100', '', 25), ('instance_dtemp', 'dtemp=75', '', 25),
                    ('model_t_abs', '', 't_abs=100', 25)]
    for name, instance, model, temp in declarations:
        folder = root/name
        folder.mkdir()
        deck = f'''BSIM4 temperature capability probe
.model NM nmos level=54 version=4.8.1 {model}
.temp {temp}
VD d 0 .5
VG g 0 1.2
M1 d g 0 0 NM l=.15u w=1u {instance}
.control
set numdgt=15
op
print i(VD)
quit
.endc
.end
'''
        (folder/'deck.sp').write_text(deck)
        run = subprocess.run([str(args.ngspice.resolve()), '-n', '-b', 'deck.sp'], cwd=folder,
            env={**os.environ, 'SPICE_SCRIPTS': str(init.resolve())}, capture_output=True, text=True, timeout=30)
        log = run.stdout+run.stderr
        (folder/'log.txt').write_text(log)
        current = re.search(r'i\(vd\)\s*=\s*([-+0-9.eE]+)', log)
        warning = bool(re.search(r'(?im)^\s*(?:warning|error):|unknown parameter|unrecognized parameter', log))
        report['cases'].append(dict(name=name, returncode=run.returncode, log_has_parameter_or_execution_warning=warning,
            clean_execution=run.returncode == 0 and not warning,
            supply_current_a=float(current[1]) if current else None,
            deck_sha256=digest(folder/'deck.sp'), log_sha256=digest(folder/'log.txt')))
    by_name = {case['name']: case for case in report['cases']}
    report.update(complete=True,
        global_temperature_control_changes_current=(all(by_name[n]['clean_execution'] for n in ('global25', 'global100')) and
            by_name['global25']['supply_current_a'] != by_name['global100']['supply_current_a']),
        tested_local_temperature_methods_accepted=[n for n in ('instance_temp', 'instance_dtemp', 'model_t_abs') if by_name[n]['clean_execution']])
    (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
