"""Summarize pad diagnostics without promoting numerical success to qualification."""

import argparse
import hashlib
import json
from pathlib import Path
import re

from validation.pad_diagnostics import METRICS
from validation.sources import write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--prior', type=Path, default=Path('docs/evidence/v06-validation.json'))
    p.add_argument('--anchor', type=Path, default=Path('results/local-multicase/bridge-reviewed/gpio_length_3mm/bridge.json'))
    args = p.parse_args()
    paths = dict(baseline=args.root / 'baseline42/report.json', matrix=args.root / 'matrix/report.json', prior=args.prior)
    baseline, matrix, prior = [json.loads(paths[k].read_text()) for k in ('baseline', 'matrix', 'prior')]
    if hashlib.sha256(args.anchor.read_bytes()).hexdigest() != matrix['frozen_inputs']['anchor_sha256']:
        raise ValueError('anchor differs from frozen simulation inputs')
    locked = {r['path']: r['sha256'] for r in json.loads(Path('tools/sources.lock.json').read_text())['files']}
    libraries = [Path(m['library']) for m in matrix['models'].values()]
    libraries.append(libraries[0].parent / 'gf_io_tt_3v3.lib')
    library_checks = {}
    for path in libraries:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = locked['pdk-v03/' + path.name]
        if actual != expected:
            raise ValueError('library differs from locked source: ' + str(path))
        library_checks[path.name] = actual
    log = (args.anchor.parent / 'sta.log').read_text()
    net = log.split('Net data\n', 1)[1].split('Net fwd\n', 1)[0]
    totals = {kind: float(re.search(kind + r' capacitance: ([\d.]+)', net)[1]) for kind in ('Pin', 'Wire', 'Total')}
    tx_self = float(re.search(r'tx_data_pad/PAD bidirect \(gf180mcu_fd_io__bi_t\) ([\d.]+)', net)[1])
    if abs(totals['Pin'] + totals['Wire'] - totals['Total']) > 1e-6 or abs(tx_self - matrix['frozen_inputs']['self_caps_pf']['gf180']) > 1e-6:
        raise ValueError('anchor net capacitance ownership differs')
    old = {r['name']: r for r in prior['records']}
    reproduced = []
    for r in baseline['records']:
        reproduced.append(dict(name=r['name'], side=r['side'], absolute_changes_ns={m: abs(r['metrics'][m] - old[r['name']]['metrics'][m]) for m in METRICS}))
    compact = []
    for name, case in matrix['cases'].items():
        fine = case['fine']
        compact.append(dict(name=name, config=case['config'], measurements=fine['source_measurements'],
                            comparisons=fine['comparisons'], step_changes_ns=case['step_changes_ns'],
                            convergence_passed=case['convergence']['passed'],
                            anchor_table_error_ns=fine.get('anchor_table_error_ns'),
                            diagnostics=fine['diagnostics'],
                            deck_sha256=fine['deck_sha256'], waveform_sha256=fine['waveform_sha256']))
    primary = [c['comparisons']['external_plus_self' if c['config']['side'] == 'gf180' else 'external_only'] for c in compact]
    gf_matrix = [c for c in compact if c['config']['role'] == 'matrix']
    alternate = [c['comparisons']['external_only'] for c in gf_matrix]
    delta_summary = {}
    for variable in ('load', 'input_slew'):
        rows = [pair['mappings']['external_plus_self']['metrics'] for pair in matrix['finite_differences'] if pair['variable'] == variable]
        delta_summary[variable] = {metric: dict(
            max_abs_residual_ns=max(abs(row[metric]['residual_ns']) for row in rows),
            max_endpoint_step_sum_ns=max(row[metric]['endpoint_step_change_sum_ns'] for row in rows),
            exceeding_observed_step_screen=sum(row[metric]['residual_exceeds_observed_step_changes'] for row in rows),
            comparisons=len(rows)) for metric in METRICS}
    report = dict(software_checks_passed=baseline['software_checks_passed'] and matrix['software_checks_passed'],
                  baseline_checks=baseline['software_checks'], matrix_checks=matrix['software_checks'],
                  transient_runs=len(baseline['records'])+len(matrix['records']), new_configurations=len(compact),
                  pad_cells=2, source=matrix['frozen_inputs']['source'],
                  source_reports_sha256={k: hashlib.sha256(path.read_bytes()).hexdigest() for k, path in paths.items()},
                  ngspice_version=matrix['frozen_inputs']['ngspice_version'], ngspice_sha256=matrix['frozen_inputs']['ngspice_sha256'],
                  source_files_sha256=matrix['frozen_inputs']['source_files_sha256'],
                  source_lock_sha256=matrix['frozen_inputs']['source_lock']['lock_sha256'],
                  source_file_count=len(matrix['frozen_inputs']['source_lock']['files']),
                  post_run_locked_liberty_verification=library_checks,
                  anchor_sha256=matrix['frozen_inputs']['anchor_sha256'],
                  anchor_load_ownership=dict(sta_log_sha256=hashlib.sha256((args.anchor.parent / 'sta.log').read_bytes()).hexdigest(),
                    pin_cap_pf=totals['Pin'], wire_cap_pf=totals['Wire'], total_cap_pf=totals['Total'], tx_inout_cap_pf=tx_self,
                    scope='STA RC network includes driver inout pin C; Ceff minus self C is the declared lumped test mapping, not a recovered physical characterization load'),
                  conventions=matrix['frozen_inputs']['conventions'], self_caps_pf=matrix['frozen_inputs']['self_caps_pf'],
                  prior_build_comparisons=reproduced,
                  max_prior_build_change_ns=max(v for r in reproduced for v in r['absolute_changes_ns'].values()),
                  max_prior_build_change_by_side_ns={side: max(v for r in reproduced if r['side'] == side for v in r['absolute_changes_ns'].values()) for side in ('gf180', 'sky130')},
                  max_halfstep_change_ns=max(v for c in compact for v in c['step_changes_ns'].values()),
                  max_definition_measurement_difference_ns=max(r['definition_measurement_error_ns'] for r in matrix['records']),
                  nominal=dict(primary_points=len(primary), primary_in_domain=sum(c['in_domain'] for c in primary),
                               primary_agreement_passed=sum(c['agreement']['passed'] for c in primary if c['in_domain']),
                               gf_matrix_points=len(gf_matrix),
                               alternate_in_domain=sum(c['in_domain'] for c in alternate),
                               alternate_agreement_passed=sum(c['agreement']['passed'] for c in alternate if c['in_domain'])),
                  cases=compact, finite_differences=matrix['finite_differences'], delta_summary=delta_summary,
                  structural_gates={k: v['closure'] for k, v in matrix['models'].items()},
                  prior_qualification_gates=baseline['qualification_gates'],
                  physical_model_qualified=False, hot_pad_timing_enabled=False,
                  scope='Finite differences are unfitted model diagnostics; timestep changes are empirical screens, not physical error bounds')
    write_json(args.root / 'summary.json', report)
    print(json.dumps({k: report[k] for k in ('software_checks_passed', 'transient_runs', 'new_configurations',
                                            'nominal', 'max_halfstep_change_ns', 'max_prior_build_change_ns', 'delta_summary')}, indent=2))
    return 0 if report['software_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
