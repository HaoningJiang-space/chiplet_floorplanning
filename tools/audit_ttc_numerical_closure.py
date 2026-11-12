"""Frozen refinement study, without reading measured temperatures or fitting."""

import argparse
import json
from pathlib import Path
import shutil
from time import perf_counter

import numpy as np
from scipy.sparse.linalg import splu

from validation.measured_sources import digest
from validation.measured_thermal import patterns
from validation.sources import git_revision, write_json
from validation.ttc_geometry import extract
from validation.ttc_separable import transfer
from validation.ttc_spatial import build


def discrepancy(prediction, reference, geometry):
    error = prediction-reference
    contrast = error-error.mean(axis=0)
    sensor, pattern = np.unravel_index(np.argmax(abs(error)), error.shape)
    return dict(max_absolute_error_k=float(np.max(abs(error))),
                max_spatial_contrast_error_k=float(np.max(abs(contrast))),
                rmse_k=float(np.sqrt(np.mean(error**2))),
                per_pattern_max_absolute_error_k=dict(zip(patterns(), np.max(abs(error), axis=0).tolist())),
                worst=dict(pattern=list(patterns())[pattern], sensor_index=int(sensor),
                           sensor_xy_um=geometry['sensors_xy_um'][sensor],
                           signed_error_k=float(error[sensor, pattern])))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('results/physical-calibration'))
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    geometry = extract(args.root/'ttc-origin')
    previous = json.loads((args.root/'ttc-observation-v2/report.json').read_text())
    code = [Path(__file__), Path('tools/validation/ttc_separable.py'), Path('tools/validation/ttc_spatial.py'),
            Path('tools/validation/ttc_spectral.py'), Path('tools/validation/ttc_geometry.py'),
            Path('tools/validation/measured_thermal.py'), Path('docs/ttc-numerical-closure-plan.md'),
            Path('tools/ttc-upstream.lock.json')]
    dependencies = [args.root/'ttc-observation-v2/report.json', args.root/'ttc-spectral-v2/report.json']
    for group in previous['groups']:
        dependencies.append(args.root/'ttc-spectral-v2'/(group+'.npz'))
    frozen = dict(git=git_revision(Path('.')), geometry=geometry,
                  code_sha256={str(p): digest(p) for p in code},
                  dependency_sha256={str(p): digest(p) for p in dependencies},
                  levels=[dict(pitch_um=500./2**i, active_cells=2**i,
                               bulk_cells=2*2**i, pad_cells=2*2**i) for i in range(5)],
                  numerical_thresholds=dict(max_error_k=.1, max_last_change_k=.05),
                  physical_model_qualified=False, measured_temperature_used=False,
                  scope='steady numerical consistency only; all lateral modes retained')
    for path in code:
        shutil.copyfile(path, args.output/path.name)
    write_json(args.output/'frozen-inputs.json', frozen)
    report = dict(frozen, groups={})
    power = np.array(list(patterns().values())).T
    for group, old in previous['groups'].items():
        parameters = old['end_refit']['fit']['parameters']
        ga = parameters['g_a_w_per_k']
        # Bath capacity has no effect on this independent steady sparse check.
        network = build(geometry, group, ga, 1.)
        direct_state = splu(network.g.tocsc()).solve(network.b)
        direct = network.h @ direct_state
        direct_residual = float(np.max(abs(network.g @ direct_state-network.b)))
        reference = np.load(args.root/'ttc-spectral-v2'/(group+'.npz'))['1024']
        saved = dict(continuum=reference, nominal_power_w=power)
        cache, sequences = {}, {}
        for kind in ('coupled', 'lateral_only', 'depth_only'):
            entries = []
            prior_prediction = None
            for level in range(5):
                ix = level if kind != 'depth_only' else 0
                iz = level if kind != 'lateral_only' else 0
                key = (ix, iz)
                if key not in cache:
                    config = dict(pitch_um=frozen['levels'][ix]['pitch_um'],
                                  active_cells=2**iz, bulk_cells=2*2**iz, pad_cells=2*2**iz)
                    start = perf_counter()
                    resistance, audit = transfer(geometry, group, ga, **config)
                    elapsed = perf_counter()-start
                    continuous_z = np.array(audit.pop('continuous_z_transfer_k_per_w'))
                    prediction = resistance @ power
                    diagnostic = continuous_z @ power
                    cache[key] = dict(configuration=config, audit=audit, elapsed_seconds=elapsed,
                                      prediction=prediction, diagnostic=diagnostic, resistance=resistance)
                current = cache[key]
                prediction = current['prediction']
                entry = {k: current[k] for k in ('configuration', 'audit', 'elapsed_seconds')}
                entry['error_to_continuum'] = discrepancy(prediction, reference, geometry)
                entry['depth_error_at_same_lateral_grid'] = discrepancy(prediction, current['diagnostic'], geometry)
                entry['lateral_error_with_continuous_depth'] = discrepancy(current['diagnostic'], reference, geometry)
                if prior_prediction is not None:
                    entry['last_refinement_max_change_k'] = float(np.max(abs(prediction-prior_prediction)))
                entries.append(entry)
                saved[kind+'_'+str(level)] = prediction
                saved[kind+'_'+str(level)+'_transfer'] = current['resistance']
                saved[kind+'_'+str(level)+'_continuous_z'] = current['diagnostic']
                prior_prediction = prediction
                print(group, kind, level, 'maxK', entry['error_to_continuum']['max_absolute_error_k'],
                      'seconds', current['elapsed_seconds'], flush=True)
                write_json(args.output/'progress.json', dict(group=group, sequence=kind, completed_level=level))
            sequences[kind] = entries
        primary_difference = float(np.max(abs((cache[(0, 0)]['resistance']-direct) @ power)))
        primary_transfer_difference = float(np.max(abs(cache[(0, 0)]['resistance']-direct)))
        final = sequences['coupled'][-1]
        screen = bool(primary_difference < 1e-7 and
                      final['error_to_continuum']['max_absolute_error_k'] < .1 and
                      final['last_refinement_max_change_k'] < .05)
        report['groups'][group] = dict(sequences=sequences,
            primary_direct_sparse_max_sensor_difference_k=primary_difference,
            primary_direct_sparse_max_transfer_difference_k_per_w=primary_transfer_difference,
            primary_direct_sparse_max_node_equation_residual=direct_residual,
            same_mesh_solver_screen=bool(primary_difference < 1e-7),
            steady_numerical_screen=screen, physical_model_qualified=False)
        np.savez_compressed(args.output/(group+'.npz'), **saved)
        write_json(args.output/'report.json', report)
    report['steady_numerical_screen'] = all(g['steady_numerical_screen'] for g in report['groups'].values())
    write_json(args.output/'report.json', report)
    print('steady_numerical_screen', report['steady_numerical_screen'], flush=True)


if __name__ == '__main__':
    main()
