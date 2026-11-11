"""Calibrate only a passive reduced network against public TTC measurements."""

import argparse
from pathlib import Path
import shutil

import numpy as np

from validation.measured_sources import verify, digest, bootstrap
from validation.measured_thermal import (CALIBRATION, GROUP_HZ, patterns, read_trace,
                                        ambient_values, endpoint, fit, predict,
                                        network_ledger, rank_report)
from validation.sources import write_json, git_revision


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('results/physical-calibration'))
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--download', action='store_true')
    args = ap.parse_args()
    lock = bootstrap(args.root) if args.download else verify(args.root)
    args.output.mkdir(parents=True, exist_ok=False)
    plan = Path('docs/measured-calibration-plan.md')
    shutil.copyfile(plan, args.output / 'frozen-plan.md')
    code = [Path(__file__), Path('tools/validation/measured_thermal.py'),
            Path('tools/validation/measured_sources.py'), Path('tools/validation/physical_invariants.py')]
    for f in code:
        shutil.copyfile(f, args.output / f.name)
    report = dict(scope='measured TTC reduced-model calibration; target chiplet unqualified',
                  physical_model_qualified=False, target_chiplet_transfer_allowed=False,
                  git=git_revision(Path('.')), source_lock=lock, plan_sha256=digest(plan),
                  code_sha256={str(f): digest(f) for f in code}, inventory=[], groups={},
                  uncertainty='resolution and calibration reference documented; complete covariance absent')
    write_json(args.output / 'frozen-inputs.json', report)
    root = args.root / 'thermal-original/release'
    for group, hz in GROUP_HZ.items():
        rows = []
        ambient = ambient_values(root / group / 'tests.txt')
        for name, nominal in patterns().items():
            path = root / group / (name + '.csv')
            v, i, t = read_trace(path)
            report['inventory'].append(dict(group=group, name=name, rows=len(v), sample_hz=hz,
                                            duration_s=len(v) / hz, sha256=digest(path)))
            if group == 'chip':
                continue
            record = dict(name=name, role='calibration' if name in CALIBRATION else 'held_out',
                          ambient_c=ambient[name], **endpoint(v, i, t, nominal, hz))
            rows.append(record)
        if group == 'chip':
            continue
        training = [r for r in rows if r['role'] == 'calibration' and r['eligible']]
        result = dict(cases=rows, calibration_names=[r['name'] for r in training], status='not_fitted')
        report['groups'][group] = result
        if len(training) < 3:
            result['reason'] = 'fewer than three eligible preregistered calibration patterns'
            continue
        p = np.array([r['power_w'] for r in training])
        y = np.array([np.array(r['temperature_c']) - r['ambient_c'] for r in training])
        log_g, fitted = fit(p, y)
        result.update(status='fitted_equivalent_network', fit=fitted)
        # Additional series resistances enter through their sum. The duplicate
        # columns are the exact structural degeneracy, regardless of noise.
        common_derivative = np.repeat(p.sum(axis=1), 16)
        result['series_resistance_nonidentifiability'] = rank_report(
            np.column_stack([common_derivative, common_derivative]))
        for r in rows:
            if 'power_w' not in r:
                continue
            prediction = predict(log_g, np.array(r['power_w'])) + r['ambient_c']
            actual = np.array(r['temperature_c'])
            err = prediction - actual
            r.update(predicted_temperature_c=prediction.tolist(), error_k=err.tolist(),
                     rmse_k=float(np.sqrt(np.mean(err**2))), bias_k=float(err.mean()),
                     max_abs_error_k=float(np.max(np.abs(err))),
                     measured_sensor_peak_c=float(actual.max()), predicted_sensor_peak_c=float(prediction.max()),
                     ledger=network_ledger(log_g, r['power_w'], r['ambient_c']))
        for role in ['calibration', 'held_out']:
            selected = [r for r in rows if r['role'] == role and r['eligible'] and 'error_k' in r]
            err = np.array([r['error_k'] for r in selected])
            result[role + '_metrics'] = dict(case_count=len(selected),
                                            rmse_k=float(np.sqrt(np.mean(err**2))) if len(selected) else None,
                                            max_abs_error_k=float(np.max(np.abs(err))) if len(selected) else None)
    write_json(args.output / 'report.json', report)
    print({g: {k: r.get(k) for k in ['status', 'calibration_metrics', 'held_out_metrics']}
           for g, r in report['groups'].items()})


if __name__ == '__main__':
    main()
