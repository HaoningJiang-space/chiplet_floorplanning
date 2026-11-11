"""Local measured TTC transient identification with frozen case holdouts."""

import argparse
import json
from pathlib import Path
import shutil

import numpy as np

from validation.measured_sources import verify, digest
from validation.measured_thermal import read_trace, CALIBRATION
from validation.measured_transient import simulate, fit, observations
from validation.sources import write_json, git_revision


def case_data(root, group, record):
    v, i, t = read_trace(root / 'thermal-original/release' / group / (record['name'] + '.csv'))
    start = max(0, record['activation_start_index'] - 600)
    power = v[start:] * i[start:]
    rise = t[start:] - record['ambient_c']
    return dict(name=record['name'], role=record['role'], power_w=power,
                temperature_rise_k=rise, initial_cells_k=rise[0], start_index=start,
                ambient_c=record['ambient_c'],
                activation_offset=record['activation_start_index'] - start,
                end_power_offset=record['activation_end_exclusive'] - start)


def metrics(error):
    return dict(rmse_k=float(np.sqrt(np.mean(error**2))), bias_k=float(error.mean()),
                max_abs_error_k=float(np.max(np.abs(error))),
                per_sensor_bias_k=error.mean(axis=0).tolist(),
                per_sensor_rmse_k=np.sqrt(np.mean(error**2, axis=0)).tolist())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('results/physical-calibration'))
    ap.add_argument('--admission', type=Path, default=Path('results/physical-calibration/thermal-fit-v2/report.json'))
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    lock = verify(args.root)
    admission = json.loads(args.admission.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    code = [Path(__file__), Path('tools/validation/measured_transient.py'),
            Path('tools/validation/measured_thermal.py'), Path('docs/measured-transient-plan.md')]
    for p in code:
        shutil.copyfile(p, args.output / p.name)
    report = dict(scope='conditional equivalent transient model; no target chiplet qualification',
                  physical_model_qualified=False, target_chiplet_transfer_allowed=False,
                  source_lock=lock, code_sha256={str(p): digest(p) for p in code},
                  git=git_revision(Path('.')), admission_report_sha256=digest(args.admission),
                  inputs_dt_s=.1, residual_sampling_s=1., groups={})
    write_json(args.output / 'frozen-inputs.json', report)
    for group, admitted in admission['groups'].items():
        cases = [case_data(args.root, group, r) for r in admitted['cases']]
        training = [c for c in cases if c['name'] in CALIBRATION]
        result = dict(calibration_names=[c['name'] for c in training], status='fitting', starts=[], cases=[])
        report['groups'][group] = result
        def progress(record):
            result['starts'].append(record)
            write_json(args.output / 'progress.json', report)
            print(group, record, flush=True)
        params, fitted = fit(training, progress)
        result.update(fit=fitted, status='conditional_equivalent_fit')
        folder = args.output / group
        folder.mkdir()
        for c in cases:
            theta, ledger = simulate(params, c['power_w'], c['initial_cells_k'], ledger=True)
            alternative, _ = simulate(params, c['power_w'], c['initial_cells_k'], alternative_initial=True)
            ix = observations(c)
            err = theta[ix, :16] - c['temperature_rise_k'][ix]
            alternative_error = alternative[ix, :16] - c['temperature_rise_k'][ix]
            activation = c['activation_offset']
            pre = c['temperature_rise_k'][:activation]
            clock = np.arange(len(pre)) * .1
            clock -= clock.mean()
            slopes = (clock @ (pre - pre.mean(axis=0)) / (clock @ clock)) if len(pre) > 1 else np.zeros(16)
            entry = dict(name=c['name'], role=c['role'], ambient_c=c['ambient_c'],
                         first_raw_index=c['start_index'], raw_sample_count=len(c['power_w']),
                         sampled_observations=len(ix), **metrics(err), ledger=ledger,
                         initial_bath_c=ledger['initial_bath_rise_k'] + c['ambient_c'],
                         pre_step_max_abs_slope_k_per_s=float(np.max(np.abs(slopes))),
                         pre_step_spatial_residual_k=(theta[:max(1, activation), :16] - c['temperature_rise_k'][:max(1, activation)]).mean(axis=0).tolist(),
                         alternative_initialization_metrics=metrics(alternative_error),
                         max_initialization_sensitivity_k=float(np.max(np.abs(theta[ix, :16] - alternative[ix, :16]))),
                         measured_sensor_peak_c=float(c['temperature_rise_k'].max() + c['ambient_c']),
                         predicted_sensor_peak_c=float(theta[:, :16].max() + c['ambient_c']))
            waveform = folder / (c['name'] + '.npz')
            np.savez_compressed(waveform, time_s=ix * .1,
                                measured_c=c['temperature_rise_k'][ix] + c['ambient_c'],
                                predicted_c=theta[ix, :16] + c['ambient_c'],
                                power_w=c['power_w'][ix], bath_c=theta[ix, 16] + c['ambient_c'])
            entry['waveform_sha256'] = digest(waveform)
            result['cases'].append(entry)
        for role in ['calibration', 'held_out']:
            selected = [r for r in result['cases'] if r['role'] == role]
            result[role + '_metrics'] = dict(case_count=len(selected),
                                            equal_run_rmse_k=float(np.sqrt(np.mean([r['rmse_k']**2 for r in selected]))),
                                            max_abs_error_k=max(r['max_abs_error_k'] for r in selected))
        write_json(args.output / 'progress.json', report)
        print(group, result['calibration_metrics'], result['held_out_metrics'], flush=True)
    write_json(args.output / 'report.json', report)


if __name__ == '__main__':
    main()
