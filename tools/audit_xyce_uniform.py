"""Complete-fabric global/local uniform-temperature counterfactual control."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from audit_integrated_transistors import build_fabric
from compare_xyce_fabric import measure
from probe_core_local_temperature import prepare_models
from chiplet_floorplanning.characterization import digest
from validation.decision_evidence import verify_saved_sta_files
from validation.xyce_output import execute, read_wave, warning_inventory


def export_control(lines, elements, temperature, local, models, output):
    """Preserve supplies, inputs and fixed RC; local export mirrors the hot exporter."""
    if Counter(l for l in lines if l.startswith(('X_', 'R_', 'C_'))) != Counter(elements):
        raise ValueError('template differs from verified complete circuit')
    if lines.count('.options device temp=25') != 1:
        raise ValueError('unexpected ambient control')
    new = []
    for line in lines:
        if not local:
            new.append(line.replace('.options device temp=25', f'.options device temp={temperature:g}'))
            continue
        if line in elements:
            continue
        if line.startswith('.lib '):
            line = f'.lib "{(models/"libs.tech/ngspice/sky130.lib.spice").resolve().as_posix()}" tt'
        elif line.startswith('.include '):
            line = f'.include "{(output/Path(line.split(chr(34))[1]).name).resolve().as_posix()}"'
        if line == '.end':
            new.extend(l+f' cell_temp_c={temperature:g}' if l.startswith('X_') else l for l in elements)
        new.append(line)
    return '\n'.join(new)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('layout', type=Path)
    parser.add_argument('cold_run', type=Path)
    parser.add_argument('transistor_source', type=Path)
    parser.add_argument('--temperature', type=float, choices=[25., 65.], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cold = json.loads((args.cold_run/'report.json').read_text())
    raw = json.loads((args.transistor_source/'report.json').read_text())
    exe = Path('local/xyce-7.10/portable/bin/Xyce.exe').resolve()
    reference = args.layout/'reference'
    sta = json.loads((reference/'report.json').read_text())
    verify_saved_sta_files(sta, reference)
    if not cold['complete'] or cold['sta_receipt_sha256'] != digest(reference/'report.json') or cold['executable_sha256'] != digest(exe) or cold['input_sha256'] != digest(args.transistor_source/'report.json'):
        raise ValueError('unmatched baseline identity')
    elements, nodes = build_fabric((reference/'fabric.v').read_text(), sta, (reference/'package.spef').read_text())
    case, = [c for c in cold['cases'] if c['step_ps'] == 2.5 and c.get('returncode') == 0]
    template = args.cold_run/'step_2.5ps'
    if set(case['artifacts_sha256']) != {'deck.cir', 'deck.cir.csv', 'xyce.log'}:
        raise ValueError('incomplete template provenance')
    for name, sha in case['artifacts_sha256'].items():
        if digest(template/name) != sha:
            raise ValueError('changed baseline artifact')
    lines = (template/'deck.cir').read_text().splitlines()
    expected_includes = [f'.include "{(args.transistor_source/(c+".spice")).resolve().as_posix()}"' for c in raw['cell_sources']]
    if Counter(l for l in lines if l.startswith('.include ')) != Counter(expected_includes):
        raise ValueError('unexpected cell includes')
    root = args.output
    root.mkdir(exist_ok=False)
    models, transforms = prepare_models(root, args.transistor_source, raw)
    report = dict(complete=False, physical_qualified=False,
        scope='uniform-temperature propagation and export-order control; fixed RC, not a thermal-layout prediction',
        temperature_c=args.temperature, step_ps=2.5, source_sha256=digest(__file__),
        executable_sha256=digest(exe), baseline_receipt_sha256=digest(args.cold_run/'report.json'),
        sta_receipt_sha256=digest(reference/'report.json'), transforms=transforms, cases=[], paths={})
    def save():
        (root/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    save()
    for name, local in (('global', False), ('local', True)):
        folder = root/name
        folder.mkdir()
        (folder/'deck.cir').write_text(export_control(lines, elements, args.temperature, local, models, root))
        result = execute(exe, folder, timeout_s=1800)
        record = dict(name=name, **result)
        report['cases'].append(record)
        record['artifacts_sha256'] = {n: digest(folder/n) for n in ('deck.cir', 'xyce.log', 'deck.cir.csv') if (folder/n).exists()}
        record['warnings'] = warning_inventory((folder/'xyce.log').read_text())
        if result['status'] != 'completed' or record['warnings']['unknown_messages']:
            report['failure_case'] = name
            record['status'] = result['status'] if result['status'] != 'completed' else 'unknown_diagnostic'
            save()
            raise ValueError('execution or diagnostic admission failed')
        try:
            wave = read_wave(folder/'deck.cir.csv', [*[f'V({n})' for n in cold['observed_nodes']], 'I(VDD)', 'I(VCLK)'])
            report['paths'][name] = measure(wave, cold['observed_nodes'], nodes, 2.5)
        except (ValueError, OSError, IndexError) as error:
            record.update(status='invalid_observation', reason=str(error), error_type=type(error).__name__)
            report['failure_case'] = name
            save()
            raise
        save()
    differences = []
    for a, b in zip(report['paths']['global'], report['paths']['local']):
        if (a['lane'], a['edge']) != (b['lane'], b['edge']):
            raise ValueError('path identity mismatch')
        differences.append(dict(lane=a['lane'], edge=a['edge'], local_minus_global_ps={
            k: (b[k]-a[k])*1000 for k in ('setup_window_ns', 'hold_window_ns', 'receiver_clock_to_q_ns')}))
    maximum = max(abs(v) for row in differences for v in row['local_minus_global_ps'].values())
    report.update(complete=True, differences=differences, max_abs_difference_ps=maximum,
        declared_numerical_screen_ps=.5, within_declared_screen=maximum <= .5,
        screen_scope='numerical equivalence diagnostic, not a physical error bound')
    save()
    print(json.dumps({k: report[k] for k in ('complete', 'temperature_c', 'max_abs_difference_ps', 'within_declared_screen')}, indent=2))


if __name__ == '__main__':
    main()
