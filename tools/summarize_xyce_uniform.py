"""Replay uniform controls without rerunning a simulator or changing raw receipts."""
import argparse
import json
from pathlib import Path

from audit_integrated_transistors import build_fabric
from audit_xyce_uniform import export_control, control_verdict
from compare_xyce_fabric import measure
from chiplet_floorplanning.characterization import digest
from validation.decision_evidence import verify_saved_sta_files
from validation.xyce_output import read_wave, warning_inventory


def summarize(root, cold_root, layout):
    report = json.loads((root/'report.json').read_text())
    cold = json.loads((cold_root/'report.json').read_text())
    sta_root = layout/'reference'
    sta = json.loads((sta_root/'report.json').read_text())
    verify_saved_sta_files(sta, sta_root)
    if (not report['complete'] or report['baseline_receipt_sha256'] != digest(cold_root/'report.json')
            or report['sta_receipt_sha256'] != digest(sta_root/'report.json')
            or report['executable_sha256'] != cold['executable_sha256']):
        raise ValueError('incomplete or unmatched uniform control')
    if report['temperature_c'] not in (25, 65) or report['step_ps'] != 2.5:
        raise ValueError('unexpected temperature/step domain')
    elements, nodes = build_fabric((sta_root/'fabric.v').read_text(), sta,
                                  (sta_root/'package.spef').read_text())
    template = cold_root/'step_2.5ps/deck.cir'
    baseline_case, = [c for c in cold['cases'] if c['step_ps'] == 2.5]
    if digest(template) != baseline_case['artifacts_sha256']['deck.cir']:
        raise ValueError('changed template')
    lines = template.read_text().splitlines()
    local_lines = (root/'local/deck.cir').read_text().splitlines()
    libline, = [line for line in local_lines if line.startswith('.lib ')]
    modelroot = Path(libline.split('"')[1]).parents[2]
    for transform in report['transforms']:
        target = (root if '/' not in transform['path'] else modelroot)/transform['path']
        if digest(target) != transform['transformed_sha256']:
            raise ValueError('modified temperature-forwarding model')
    if sorted(c['name'] for c in report['cases']) != ['global', 'local']:
        raise ValueError('incomplete case domain')
    paths, cases = {}, []
    for name, local in (('global', False), ('local', True)):
        folder = root/name
        record, = [c for c in report['cases'] if c['name'] == name]
        if record['status'] != 'completed' or record['returncode'] != 0:
            raise ValueError('failed control')
        if set(record['artifacts_sha256']) != {'deck.cir', 'xyce.log', 'deck.cir.csv'}:
            raise ValueError('incomplete artifact domain')
        for artifact, sha in record['artifacts_sha256'].items():
            if digest(folder/artifact) != sha:
                raise ValueError('modified raw control artifact')
        expected = export_control(lines, elements, report['temperature_c'], local, modelroot, root)
        if (folder/'deck.cir').read_text() != expected:
            raise ValueError('control changed circuit or stimulus')
        warnings = warning_inventory((folder/'xyce.log').read_text())
        if warnings['unknown_messages']:
            raise ValueError('unknown/suppressed diagnostics')
        columns = [*[f'V({n})' for n in cold['observed_nodes']], 'I(VDD)', 'I(VCLK)']
        paths[name] = measure(read_wave(folder/'deck.cir.csv', columns), cold['observed_nodes'], nodes, 2.5)
        if paths[name] != report['paths'][name]:
            raise ValueError('saved measurements differ from replay')
        cases.append(dict(name=name, warning_count=len(warnings['messages']),
                          unknown_warning_count=0, artifacts_sha256=record['artifacts_sha256']))
    differences = []
    for a, b in zip(paths['global'], paths['local']):
        if (a['lane'], a['edge']) != (b['lane'], b['edge']):
            raise ValueError('path identity mismatch')
        differences.append(dict(lane=a['lane'], edge=a['edge'], local_minus_global_ps={
            k: (b[k]-a[k])*1000 for k in ('setup_window_ns', 'hold_window_ns', 'receiver_clock_to_q_ns')}))
    maximum = max(abs(v) for row in differences for v in row['local_minus_global_ps'].values())
    if differences != report['differences'] or maximum != report['max_abs_difference_ps']:
        raise ValueError('saved difference differs from replay')
    return dict(**control_verdict(True, maximum), temperature_c=report['temperature_c'],
        source_receipt_sha256=digest(root/'report.json'), step_ps=2.5,
        declared_numerical_screen_ps=.5, max_abs_difference_ps=maximum,
        scope='uniform propagation/export control at fixed RC; not a physical error bound',
        cases=cases, differences=differences)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', type=Path, nargs=2)
    parser.add_argument('--cold', type=Path, required=True)
    parser.add_argument('--layout', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = [summarize(root, args.cold, args.layout) for root in args.runs]
    if sorted(r['temperature_c'] for r in rows) != [25, 65]:
        raise ValueError('both control temperatures required')
    result = dict(source_sha256=digest(__file__), execution_complete=True,
        numerical_control_passed=all(r['numerical_control_passed'] for r in rows),
        physical_qualified=False, controls=rows)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps([{k: v for k, v in r.items() if k not in ('cases', 'differences')} for r in rows], indent=2))


if __name__ == '__main__':
    main()
