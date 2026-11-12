"""Validate local operating-temperature propagation through pinned SKY130 wrappers."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np

from chiplet_floorplanning.characterization import digest
from validation.xyce_output import read_wave, execute, warning_inventory
from compare_xyce_core import measure
from audit_core_ff_spice import measure as measure_ff


def instrument(text, primitive=False):
    """Add only temperature forwarding; reject unexpected topology/syntax."""
    lines = text.splitlines(keepends=True)
    declaration = ' device_temp_c=25' if primitive else ' cell_temp_c=25'
    suffix = ' temp={device_temp_c}' if primitive else ' device_temp_c={cell_temp_c}'
    heads = [i for i, line in enumerate(lines) if line.lower().startswith('.subckt ')]
    devices = [i for i, line in enumerate(lines) if line[:1].lower() == ('m' if primitive else 'x')]
    if len(heads) != 1 or not devices or (primitive and len(devices) != 1):
        raise ValueError('unexpected wrapper topology')
    if 'device_temp_c' in text or 'cell_temp_c' in text:
        raise ValueError('temperature parameter already present')
    for i in devices:
        if not primitive and not any(p in lines[i] for p in ('sky130_fd_pr__nfet_01v8 ', 'sky130_fd_pr__pfet_01v8_hvt ')):
            raise ValueError('unhandled primitive')
    edits = {heads[0]: ' params:'+declaration, **{i: suffix for i in devices}}
    original = list(lines)
    for i, addition in edits.items():
        lines[i] = lines[i].rstrip('\r\n')+addition+'\n'
    # Strip only declared additions and require every original token to remain.
    restored = list(lines)
    for i, addition in edits.items():
        restored[i] = restored[i].removesuffix(addition+'\n')+('\n' if original[i].endswith('\n') else '')
    if ''.join(restored) != text:
        raise ValueError('instrumentation changed non-temperature content')
    return ''.join(lines), len(devices)


def prepare_models(root, refroot, ref):
    source = Path('local/pad-spice')
    for name, sha in ref['primitive_sources']['files'].items():
        if digest(source/name) != sha:
            raise ValueError('changed primitive source')
    # Keep Windows include paths no longer than the pinned source tree.
    models = Path('local')/('xt-'+hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:8])
    shutil.copytree(source/'sky130A', models)
    transforms = []
    for device in ('nfet_01v8', 'pfet_01v8_hvt'):
        name = f'libs.ref/sky130_fd_pr/spice/sky130_fd_pr__{device}__tt.pm3.spice'
        path = models/name
        old = digest(path)
        changed, count = instrument(path.read_text(), primitive=True)
        path.write_text(changed)
        transforms.append(dict(path=name, original_sha256=old, transformed_sha256=digest(path), devices=count))
    for cell, (_, sha) in ref['cell_sources'].items():
        original = refroot/(cell+'.spice')
        if digest(original) != sha:
            raise ValueError('changed cell')
        changed, count = instrument(original.read_text())
        target = root/(cell+'.spice')
        target.write_text(changed)
        transforms.append(dict(path=cell+'.spice', original_sha256=sha, transformed_sha256=digest(target), devices=count))
    return models, transforms


def observe_case(report, root, folder, name, cell):
    """Keep rejected observations as evidence, without manufacturing measurements."""
    try:
        columns = (['V(clk)', 'V(d)', 'V(q1)', 'V(q2)', 'I(VDD1)', 'I(VDD2)', 'I(VCLK)', 'I(VD)']
                   if cell == 'dfxtp_1' else
                   ['V(vin)', 'V(out1)', 'V(out2)', 'I(VDD1)', 'I(VDD2)', 'I(VIN)'])
        wave = read_wave(folder/'deck.cir.csv', columns)
        return ([measure_ff(wave[:, [0, 1, 2, col, col+2, 7, 8]]) for col in (3, 4)]
                if cell == 'dfxtp_1' else
                [measure(wave[:, [0, 1, col, col+2, 6]], cell, .122474) for col in (2, 3)])
    except (ValueError, OSError, IndexError) as error:
        report['cases'].append(dict(name=name, status='invalid_observation',
            error_type=type(error).__name__, reason=str(error),
            artifacts_sha256={n: digest(folder/n) for n in ('deck.cir', 'deck.cir.csv', 'xyce.log') if (folder/n).exists()}))
        report.update(complete=False, forwarding_controls_pass=False, failure_case=name)
        (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cell', choices=['inv_1', 'buf_8', 'dfxtp_1'], default='inv_1')
    args = parser.parse_args()
    root = args.output
    root.mkdir(exist_ok=False)
    refroot = Path('results/physical-calibration/integrated-transistors-v1')
    ref = json.loads((refroot/'report.json').read_text())
    source = Path('local/pad-spice')
    models, transforms = prepare_models(root, refroot, ref)
    exe = Path('local/xyce-7.10/portable/bin/Xyce.exe').resolve()
    report = dict(complete=False, physical_qualified=False, source_sha256=digest(__file__),
        executable_sha256=digest(exe), primitive_manifest_reference_sha256=digest(refroot/'report.json'),
        transforms=transforms, cell=args.cell, cases=[], scope='actual cell temperature forwarding controls, not hot-layout or Pad validation')
    for name, global_temp, temps, modified in (
        ('global25', 25, (None, None), False), ('global100', 100, (None, None), False),
        ('local25', 25, (25, 25), True), ('local100', 25, (100, 100), True),
        ('mixed', 25, (25, 100), True), ('mixed_reverse', 25, (100, 25), True),
    ):
        folder = root/name
        folder.mkdir()
        library = (models if modified else source/'sky130A')/'libs.tech/ngspice/sky130.lib.spice'
        cellpath = (root if modified else refroot)/(args.cell+'.spice')
        suffixes = ['' if t is None else f' cell_temp_c={t}' for t in temps]
        deck = f'''Two actual SKY130 inverters: temperature forwarding control
.lib "{library.resolve().as_posix()}" tt
.include "{cellpath.resolve().as_posix()}"
.options parser scale=1u
.options nonlin reltol=1e-6 abstol=1e-13
.options nonlin-tran reltol=1e-6 abstol=1e-13
.options device temp={global_temp}
VDD1 vdd1 0 1.8
VDD2 vdd2 0 1.8
VIN vin 0 PWL(0 0 2n 0 2.2041233333333334n 1.8 6n 1.8 6.204123333333333n 0 10n 0)
XA vin 0 0 vdd1 vdd1 out1 sky130_fd_sc_hd__{args.cell}{suffixes[0]}
XB vin 0 0 vdd2 vdd2 out2 sky130_fd_sc_hd__{args.cell}{suffixes[1]}
C1 out1 0 .0254232p
C2 out2 0 .0254232p
.tran 1p 10n 0 1p
.print tran format=csv precision=16 V(vin) V(out1) V(out2) I(VDD1) I(VDD2) I(VIN)
.end
'''
        if args.cell == 'dfxtp_1':
            # Same initialized 0 / captured 1 / captured 0 sequence as the CQ audit.
            clock = '0 0 '
            for start in (1., 7., 13.):
                clock += f'{start}n 0 {start+.2}n 1.8 {start+2}n 1.8 {start+2.2}n 0 '
            clock += '18n 0'
            prefix = deck.split('VIN vin')[0]
            deck = prefix+f'''VCLK clk 0 PWL({clock})
VD d 0 PWL(0 0 5n 0 5.2n 1.8 11n 1.8 11.2n 0 18n 0)
XA clk d 0 0 vdd1 vdd1 q1 sky130_fd_sc_hd__dfxtp_1{suffixes[0]}
XB clk d 0 0 vdd2 vdd2 q2 sky130_fd_sc_hd__dfxtp_1{suffixes[1]}
C1 q1 0 .0254232p
C2 q2 0 .0254232p
.tran 1p 18n 0 1p
.print tran format=csv precision=16 V(clk) V(d) V(q1) V(q2) I(VDD1) I(VDD2) I(VCLK) I(VD)
.end
'''
        (folder/'deck.cir').write_text(deck)
        execution = execute(exe, folder)
        if execution['status'] != 'completed':
            report['cases'].append(dict(name=name, **execution,
                artifacts_sha256={n: digest(folder/n) for n in ('deck.cir', 'xyce.log')}))
            report.update(complete=False, forwarding_controls_pass=False, failure_case=name)
            (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
            raise ValueError('execution failed: '+name)
        metrics = observe_case(report, root, folder, name, args.cell)
        report['cases'].append(dict(name=name, global_temperature_c=global_temp, local_temperatures_c=temps,
            metrics_ns=metrics, warnings=warning_inventory((folder/'xyce.log').read_text()),
            warning_count=len(re.findall('Netlist warning', (folder/'xyce.log').read_text())),
            artifacts_sha256={n: digest(folder/n) for n in ('deck.cir', 'deck.cir.csv', 'xyce.log')}))
        (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    byname = {r['name']: r for r in report['cases']}
    checks = []
    for name, expected in (('local25', ('global25', 'global25')), ('local100', ('global100', 'global100')),
                           ('mixed', ('global25', 'global100')), ('mixed_reverse', ('global100', 'global25'))):
        for index, reference in enumerate(expected):
            delta = {k: (v-byname[reference]['metrics_ns'][index][k])*1000 for k, v in byname[name]['metrics_ns'][index].items()}
            checks.append(dict(case=name, instance=index, reference=reference, differences_ps=delta,
                within_0_05ps=all(abs(v) <= .05 for v in delta.values())))
    distinct = any(abs(byname['global100']['metrics_ns'][0][k]-v)*1000 > .05
                   for k, v in byname['global25']['metrics_ns'][0].items())
    report.update(complete=True, checks=checks, global_temperature_controls_distinct=distinct,
        forwarding_controls_pass=distinct and all(r['within_0_05ps'] for r in checks)
            and not any(r['warnings']['unknown_messages'] for r in report['cases']),
        tolerance_ps=.05, tolerance_scope='declared numerical equivalence screen, not a physical uncertainty bound')
    (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('cases', 'transforms')}, indent=2))
    return 0 if report['forwarding_controls_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
