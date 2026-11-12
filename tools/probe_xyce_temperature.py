"""Test independent BSIM4 operating temperatures, without claiming PDK calibration."""
import argparse
import csv
import json
import math
from pathlib import Path
import re
import subprocess

from chiplet_floorplanning.characterization import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--separate-models', action='store_true', help='Identical independent model cards for the two devices')
    parser.add_argument('--bsim-version', choices=['4.8.2', '4.5'], default='4.8.2')
    parser.add_argument('--xyce', type=Path, default=Path('local/xyce-7.10/portable/bin/Xyce.exe'))
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False)
    report = dict(complete=False, physical_calibration=False,
                  scope='manufactured BSIM4 parameter semantics, not PDK or timing validation',
                  source_sha256=digest(__file__), executable_sha256=digest(args.xyce),
                  separate_models=args.separate_models, bsim_version=args.bsim_version, cases=[])
    for name, ambient, first, second in (
        ('global25', 25, '', ''), ('global100', 100, '', ''),
        ('local100', 25, 'TEMP=100', 'TEMP=100'),
        ('offset75', 25, 'DTEMP=75', 'DTEMP=75'),
        ('mixed', 25, 'TEMP=25', 'TEMP=100'),
        ('mixed_reverse', 25, 'TEMP=100', 'TEMP=25'),
    ):
        folder = args.output/name
        folder.mkdir()
        parameters = f'nmos level=54 version={args.bsim_version} pbswgs=.1 pbswgd=.1'
        extra_model = '.model NM2 '+parameters if args.separate_models else ''
        second_model = 'NM2' if args.separate_models else 'NM'
        deck = f'''Independent BSIM4 temperature probe
.model NM {parameters}
{extra_model}
.options device temp={ambient}
VD1 d1 0 .5
VD2 d2 0 .5
VG g 0 1.2
M1 d1 g 0 0 NM l=.15u w=1u {first}
M2 d2 g 0 0 {second_model} l=.15u w=1u {second}
.dc VG 1.2 1.2 .1
.print dc format=csv precision=16 I(VD1) I(VD2)
.end
'''
        (folder/'deck.cir').write_text(deck)
        run = subprocess.run([str(args.xyce.resolve()), 'deck.cir'], cwd=folder,
                             capture_output=True, text=True, timeout=60)
        log = run.stdout+run.stderr
        (folder/'log.txt').write_text(log)
        warning = bool(re.search(r'(?i)warning|error|unrecognized|unknown parameter', log))
        datafile = folder/'deck.cir.csv'
        currents = None
        if datafile.exists():
            rows = list(csv.DictReader(datafile.open()))
            if len(rows) == 1:
                currents = [float(rows[0][k]) for k in ('I(VD1)', 'I(VD2)')]
        report['cases'].append(dict(name=name, ambient_c=ambient, instance_parameters=[first, second],
            returncode=run.returncode, clean_execution=run.returncode == 0 and not warning,
            supply_currents_a=currents, deck_sha256=digest(folder/'deck.cir'),
            log_sha256=digest(folder/'log.txt'), output_sha256=digest(datafile) if datafile.exists() else None))
    cases = {c['name']: c for c in report['cases']}
    valid = all(c['clean_execution'] and c['supply_currents_a'] is not None and
                all(math.isfinite(v) for v in c['supply_currents_a']) for c in cases.values())
    checks = {}
    if valid:
        cold = cases['global25']['supply_currents_a'][0]
        hot = cases['global100']['supply_currents_a'][0]
        close = lambda a, b: math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-15)
        checks['global_controls_distinct'] = not close(cold, hot)
        expected = dict(global25=[cold, cold], global100=[hot, hot], local100=[hot, hot],
                        offset75=[hot, hot], mixed=[cold, hot], mixed_reverse=[hot, cold])
        for name, values in expected.items():
            checks[name+'_matches'] = all(close(a, b) for a, b in zip(cases[name]['supply_currents_a'], values))
    report.update(complete=True, all_runs_clean=valid, checks=checks,
                  local_temperature_controls_pass=valid and bool(checks) and all(checks.values()),
                  comparison_tolerance=dict(relative=1e-9, absolute_a=1e-15))
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return 0 if report['local_temperature_controls_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
