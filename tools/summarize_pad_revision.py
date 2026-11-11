"""Compact, hash-rechecked evidence for provenance, revision and physical checks."""

import argparse
import json
from pathlib import Path
import re

from validation.pad_diagnostics import METRICS
from validation.pad_sources import digest
from validation.sources import write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=Path('results/characterization-provenance'))
    p.add_argument('--revision-dir', default='revision-controls-v2')
    p.add_argument('--test-log', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    r = args.root
    inputs = {name: r / path for name, path in (
        ('provenance', 'provenance.json'), ('revision', args.revision_dir + '/report.json'),
        ('devices', 'device-semantics/report.json'), ('physics', 'physical-invariants.json'))}
    raw = {name: json.loads(path.read_text()) for name, path in inputs.items()}
    rev = raw['revision']
    prior_path = Path(rev['frozen_inputs']['baseline_path'])
    if digest(prior_path.read_bytes()) != rev['frozen_inputs']['baseline_sha256']:
        raise ValueError('baseline report changed')
    prior = json.loads(prior_path.read_text())
    for record in rev['records']:
        folder = r / args.revision_dir / record['variant'] / record['name']
        for file, key in [('deck.sp', 'deck_sha256'), ('ngspice.log', 'log_sha256'),
                          ('waveform.txt', 'waveform_sha256'), ('nor_activity.txt', 'activity_sha256')]:
            if digest((folder / file).read_bytes()) != record[key]:
                raise ValueError('experiment artifact changed: ' + str(folder / file))
    for variant, metadata in rev['frozen_inputs']['variants'].items():
        if digest((r / args.revision_dir / (variant + '.spice')).read_bytes()) != metadata['sha256']:
            raise ValueError('derived netlist changed')
    cases = []
    for case_id in ('sky_nominal', 'sky130_anchor_rise', 'sky130_anchor_fall'):
        baseline = prior['cases'][case_id]
        entry = dict(case_id=case_id, config=baseline['config'],
                     baseline_metrics_ns={m: baseline['fine']['source_measurements'][m] for m in METRICS},
                     liberty_metrics_ns=baseline['fine']['comparisons']['external_only']['metrics'], variants={})
        for row in rev['cases']:
            if row['case_id'] != case_id:
                continue
            fine = row['fine']
            entry['variants'][row['variant']] = dict(metrics_ns={m: fine['source_measurements'][m] for m in METRICS},
                signed_change_ns=fine['signed_change_from_baseline_ns'], step_changes_ns=row['step_changes_ns'],
                empirical_delta_screen_ns=row['empirical_delta_screen_ns'],
                nominal_agreement=fine['comparison']['agreement']['passed'],
                nominal_errors_ns={m: fine['comparison']['agreement']['metrics'][m]['error_ns'] for m in METRICS},
                diagnostics=fine['diagnostics'], internal_node_activity_v=fine['internal_node_activity_v'])
        cases.append(entry)
    test_log = args.test_log.read_text(encoding='utf-8-sig')
    match = re.search(r'Ran (\d+) tests', test_log)
    if not match or not re.search(r'\nOK\s*$', test_log):
        raise ValueError('unit-test log is incomplete or failed')
    test_count = int(match[1])
    thermal = raw['physics']['thermal_cases']
    summary = dict(
        source=rev['frozen_inputs']['source'], analyzed_remote_commit='c124aa982eb97f49a7f4be907554c94436ace2d2',
        fetch_succeeded=True, local_only=True,
        source_reports={name: dict(path=str(path), sha256=digest(path.read_bytes())) for name, path in inputs.items()},
        unit_tests=dict(passed=test_count, log_sha256=digest(args.test_log.read_bytes())),
        source_checks=raw['provenance']['software_checks'],
        provenance_sources=raw['provenance']['locked_sources'],
        library_headers=raw['provenance']['library_headers'],
        tree_inventories=raw['provenance']['tree_inventories'], archive_inventories=raw['provenance']['archive_inventories'],
        original_characterization_contract=raw['provenance']['original_characterization_contract'],
        empty_reachable_io_definitions=raw['provenance']['empty_reachable_io_definitions'],
        changed_definitions=raw['provenance']['changed_definitions'],
        new_pad_transients=len(rev['records']), reused_baseline_transients=6,
        new_configuration_count=len(rev['cases']), revision_software_checks=rev['software_checks'],
        artifact_hashes_rechecked=True, pad_cases=cases,
        maximum_revision_step_change_ps=max(v * 1000 for c in cases for d in c['variants'].values() for v in d['step_changes_ns'].values()),
        maximum_absolute_delay_change_ps=max(abs(v) * 1000 for c in cases for d in c['variants'].values() for m, v in d['signed_change_ns'].items() if 'delay' in m),
        maximum_nor_vs_all_metric_difference_ns=max(abs(c['variants']['nor_only']['metrics_ns'][m] - c['variants']['reachable_updates']['metrics_ns'][m]) for c in cases for m in METRICS),
        nominal_agreement_passed=sum(d['nominal_agreement'] for c in cases for d in c['variants'].values()),
        device_semantics={k: raw['devices'][k] for k in ('software_checks_passed', 'pfet_current_ratios', 'resistor_ohms', 'diagnostics')},
        thermal_invariants=[{k: case[k] for k in ('name', 'node_count', 'peak_c', 'ledger', 'necessary_invariants_passed')} for case in thermal],
        channel_scale_checks=raw['physics']['channel_scale_checks'],
        original_characterization_recovered=False, physical_model_qualified=False, hot_pad_timing_enabled=False,
        supervision=dict(skill='codex-chatgpt-skill', conversation_url='https://chatgpt.com/c/6af41d50-059c-83e8-92e6-eb975244c865',
                         scope='plan and interpretation review; reviewer did not independently reproduce local experiments'),
        scope='source-supported counterfactuals and necessary invariants; no full PDK upgrade, physical calibration or lane error bound')
    if not (all(summary['source_checks'].values()) and all(summary['revision_software_checks'].values()) and
            summary['device_semantics']['software_checks_passed'] and all(t['necessary_invariants_passed'] for t in summary['thermal_invariants'])):
        raise ValueError('cannot summarize milestone with failed required checks')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, summary)
    print(json.dumps({k: summary[k] for k in ('new_pad_transients', 'new_configuration_count',
          'maximum_revision_step_change_ps', 'maximum_absolute_delay_change_ps',
          'maximum_nor_vs_all_metric_difference_ns', 'nominal_agreement_passed')}, indent=2))


if __name__ == '__main__':
    main()
