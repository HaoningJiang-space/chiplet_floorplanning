"""Post-fit sensitivity diagnostics; never change fitted parameters or split."""

import argparse
import json
from pathlib import Path
import shutil

import numpy as np

from calibrate_measured_transient import case_data, metrics
from validation.measured_sources import verify, digest
from validation.measured_transient import simulate, residual
from validation.sources import write_json


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('results/physical-calibration'))
    ap.add_argument('--fit', type=Path, default=Path('results/physical-calibration/thermal-transient-v1/report.json'))
    ap.add_argument('--admission', type=Path, default=Path('results/physical-calibration/thermal-fit-v2/report.json'))
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    verify(args.root)
    report = json.loads(args.fit.read_text())
    admission = json.loads(args.admission.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, args.output / 'audit_measured_transient.py')
    shutil.copyfile('docs/measured-transient-plan.md', args.output / 'plan.md')
    audit = dict(fit_report_sha256=digest(args.fit), refitted=False,
                 plan_sha256=digest('docs/measured-transient-plan.md'), groups={})
    write_json(args.output / 'frozen-inputs.json', audit)
    for group, fitted in report['groups'].items():
        keys = ['g_xy_w_per_k', 'g_z_w_per_k', 'g_a_w_per_k', 'c_cell_j_per_k', 'c_bath_j_per_k']
        params = np.log([fitted['fit']['parameters'][key] for key in keys])
        cases = [case_data(args.root, group, r) for r in admission['groups'][group]['cases']]
        result = dict(cases=[], capacity_objective_slice=[])
        audit['groups'][group] = result
        for case in cases:
            p, y = case['power_w'], case['temperature_rise_k']
            pred, _ = simulate(params, p, case['initial_cells_k'])
            err = pred[:, :16] - y
            start, end = case['activation_offset'], case['end_power_offset']
            native = np.arange(len(p))
            masks = dict(baseline=native < start, powered=(native >= start) & (native < end),
                         cooldown=native >= end,
                         outside_transition_1s=(np.abs(native - start) > 10) & (np.abs(native - end) > 10))
            row = dict(name=case['name'], role=case['role'], native_metrics=metrics(err),
                       phases={name: dict(samples=int(mask.sum()), **metrics(err[mask]))
                               for name, mask in masks.items() if np.any(mask)}, timing_scenarios=[])
            loc = np.unravel_index(np.argmax(np.abs(err)), err.shape)
            row['worst_residual_location'] = dict(time_from_start_s=float(loc[0] * .1), sensor_index=int(loc[1]),
                                                 signed_error_k=float(err[loc]),
                                                 distance_to_principal_event_s=float(min(abs(loc[0] - start), abs(loc[0] - end)) * .1))
            pre = y[:start].mean(axis=1)
            time = np.arange(len(pre)) * .1
            time -= time.mean()
            slope = float(time @ (pre - pre.mean()) / (time @ time)) if len(pre) > 1 else 0.
            row.update(pre_step_mean_slope_k_per_s=slope,
                       approximate_initial_bath_correction_k=float(np.exp(params[3] - params[1]) * slope))
            for shift in [-1, 1]:
                shifted = p[np.clip(native - shift, 0, len(p) - 1)]
                alternative, _ = simulate(params, shifted, case['initial_cells_k'])
                row['timing_scenarios'].append(dict(power_shift_s=shift * .1,
                                                     max_prediction_change_k=float(np.max(np.abs(alternative[:, :16] - pred[:, :16]))),
                                                     **metrics(alternative[:, :16] - y)))
            result['cases'].append(row)
        training = [c for c in cases if c['role'] == 'calibration']
        for capacity in [1e-4, 1e-3, .01, .1, 1]:
            changed = params.copy()
            changed[3] = np.log(capacity)
            error = residual(changed, training)
            result['capacity_objective_slice'].append(dict(c_cell_j_per_k=capacity,
                                                           equal_run_rmse_k=float(np.sqrt(error @ error / len(training)))))
    write_json(args.output / 'report.json', audit)
    print({g: r['capacity_objective_slice'] for g, r in audit['groups'].items()})


if __name__ == '__main__':
    main()
