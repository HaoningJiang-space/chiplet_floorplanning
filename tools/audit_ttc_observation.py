"""Source-selected interval-end TTC audit; all experiments run locally."""

import argparse
import json
from pathlib import Path
import shutil

import numpy as np

from calibrate_measured_transient import case_data
from validation.measured_sources import verify, digest
from validation.measured_thermal import CALIBRATION
from validation.measured_transient import observations
from validation.ttc_geometry import extract, bootstrap
from validation.ttc_observation import simulate, fit, raw_metrics, OPERATORS, PARAMETERS
from validation.sources import write_json, git_revision


def summarize(records):
    result = {}
    for role in ('calibration', 'held_out'):
        for subset in ('all', 'upstream_range'):
            selected = [r for r in records if r['role'] == role
                        and (subset == 'all' or r['name'] != 'sixteen')]
            metrics = {}
            for grid in ('native', 'one_second', 'after_conditioned_second'):
                metrics[grid] = dict(case_count=len(selected),
                    equal_run_mae_k=float(np.mean([r[grid]['mae_k'] for r in selected])),
                    equal_run_rmse_k=float(np.sqrt(np.mean([r[grid]['rmse_k']**2 for r in selected]))),
                    max_abs_error_k=max(r[grid]['max_abs_error_k'] for r in selected))
            result[role+'_'+subset] = metrics
    return result


def evaluate(params, cases, operator, folder=None):
    entries = []
    for case in cases:
        theta, ledger = simulate(params, case['power_w'], case['initial_cells_k'], operator, True)
        error = theta[:, :16] - case['temperature_rise_k']
        ix = observations(case)
        worst = np.unravel_index(np.argmax(np.abs(error)), error.shape)
        entry = dict(name=case['name'], role=case['role'], native=raw_metrics(error),
                     one_second=raw_metrics(error[ix]),
                     after_conditioned_second=raw_metrics(error[10:]), ledger=ledger,
                     worst=dict(relative_row=int(worst[0]), raw_row=int(worst[0]+case['start_index']),
                                nominal_row_time_s=float(worst[0]*.1), sensor_index=int(worst[1]),
                                signed_error_k=float(error[worst])),
                     measured_peak_c=float(case['temperature_rise_k'].max()+case['ambient_c']),
                     predicted_peak_c=float(theta[:, :16].max()+case['ambient_c']))
        if folder:
            # Keep native samples around both power transitions, plus the
            # previous reporting grid. This exposes, rather than hides, spikes.
            event_ix = np.unique(np.r_[ix, np.arange(max(0, case['activation_offset']-20),
                                                    min(len(error), case['activation_offset']+21)),
                                      np.arange(max(0, case['end_power_offset']-20),
                                                min(len(error), case['end_power_offset']+21))])
            wave = folder/(case['name']+'.npz')
            np.savez_compressed(wave, nominal_row_time_s=event_ix*.1,
                                measured_c=case['temperature_rise_k'][event_ix]+case['ambient_c'],
                                predicted_c=theta[event_ix, :16]+case['ambient_c'],
                                power_w=case['power_w'][event_ix],
                                event_times_s=np.array([case['activation_offset'], case['end_power_offset']])*.1)
            entry['waveform_sha256'] = digest(wave)
        entries.append(entry)
    return dict(cases=entries, metrics=summarize(entries))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('results/physical-calibration'))
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--bootstrap-upstream', action='store_true')
    ap.add_argument('--baseline', type=Path, default=Path('results/physical-calibration/thermal-transient-v1/report.json'))
    ap.add_argument('--admission', type=Path, default=Path('results/physical-calibration/thermal-fit-v2/report.json'))
    args = ap.parse_args()
    verify(args.root)
    if args.bootstrap_upstream:
        bootstrap(args.root/'ttc-origin')
    geometry = extract(args.root/'ttc-origin')
    previous = json.loads(args.baseline.read_text())
    admission = json.loads(args.admission.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    code = [Path(__file__), Path('tools/validation/ttc_observation.py'), Path('tools/validation/ttc_geometry.py'),
            Path('tools/calibrate_measured_transient.py'), Path('tools/validation/measured_transient.py'),
            Path('tools/validation/measured_thermal.py'), Path('docs/ttc-observation-plan.md'),
            Path('tools/ttc-upstream.lock.json'), Path('tools/measured-sources.lock.json')]
    for p in code:
        shutil.copyfile(p, args.output/p.name)
    report = dict(physical_model_qualified=False, target_chiplet_transfer_allowed=False,
                  claim='sensitivity to author evaluation convention; hardware timing remains unverified',
                  observation_selection='end chosen from upstream before new predictions',
                  validation_status='previously examined held-out patterns; not blind validation',
                  smoothing=False, primary_exclusions=[], dt_s=.1, residual_sampling_s=1.,
                  initial_state='first measured cell values interpreted as pre-interval conditional state',
                  git=git_revision(Path('.')), geometry=geometry,
                  code_sha256={str(p): digest(p) for p in code},
                  baseline_sha256=digest(args.baseline), admission_sha256=digest(args.admission), groups={})
    write_json(args.output/'frozen-inputs.json', report)
    for group, admitted in admission['groups'].items():
        cases = [case_data(args.root, group, r) for r in admitted['cases']]
        result = dict(fixed_parameters=previous['groups'][group]['fit']['parameters'], fixed={}, starts=[])
        report['groups'][group] = result
        old_params = np.log([result['fixed_parameters'][key] for key in PARAMETERS])
        for operator in OPERATORS:
            result['fixed'][operator] = evaluate(old_params, cases, operator)
            print(group, 'fixed', operator, result['fixed'][operator]['metrics']['held_out_all']['native'], flush=True)
        write_json(args.output/'progress.json', report)
        def progress(record):
            result['starts'].append(record)
            write_json(args.output/'progress.json', report)
            print(group, 'end fit', record, flush=True)
        params, fitted = fit([c for c in cases if c['name'] in CALIBRATION], progress)
        folder = args.output/group
        folder.mkdir()
        result['end_refit'] = dict(fit=fitted, **evaluate(params, cases, 'end', folder))
        write_json(args.output/'progress.json', report)
        print(group, 'end refit', result['end_refit']['metrics'], flush=True)
    write_json(args.output/'report.json', report)


if __name__ == '__main__':
    main()
