"""Frozen full-package numerical controls and exploratory measured DC contrast."""

import argparse
import gc
import json
from pathlib import Path
import shutil

import numpy as np

from validation.measured_sources import digest, verify
from validation.measured_thermal import patterns, read_trace
from validation.sources import git_revision, write_json
from validation.ttc_geometry import extract
from validation.ttc_package import source_boundary, build, solve
from validation.ttc_separable import transfer as fv_transfer
from validation.ttc_spectral import transfer as continuum_transfer


def projection(values):
    return values-values.mean(axis=0, keepdims=True)


def measured_diagnostic(resistance, previous, root, group):
    cases = []
    for record in previous['groups'][group]['cases']:
        power = np.array(record['power_w'])
        observed = np.array(record['measured_sensor_difference_k'])
        prediction = projection(resistance @ power[:, None]).ravel()
        v, i, t = read_trace(root/'thermal-original/release'/group/(record['name']+'.csv'))
        start, end = record['start_raw_row'], record['end_raw_row_exclusive']
        mean_temperature = t[start:end].mean(axis=1)
        # Two 4.5 s half-window means have centers separated by 4.5 s.
        common_slope = (mean_temperature[45:].mean()-mean_temperature[:45].mean())/4.5
        cases.append(dict(name=record['name'], role=record['role'],
                          source_power_domain=bool(power.sum() < 40), total_power_w=float(power.sum()),
                          elapsed_since_activation_s=record['elapsed_since_activation_s'],
                          common_temperature_slope_k_per_s=float(common_slope),
                          approximate_dc_only=True, temperature_difference_k=prediction.tolist(),
                          rmse_k=float(np.sqrt(np.mean((prediction-observed)**2))),
                          uniform_continuum_rmse_k=record['continuum_error']['rmse_k'],
                          reduced_baseline_rmse_k=record['baseline_error']['rmse_k']))
    summary = {}
    for role in ('calibration', 'held_out'):
        for domain in ('all', 'below_40w'):
            subset = [c for c in cases if c['role'] == role and (domain == 'all' or c['source_power_domain'])]
            rmse = float(np.sqrt(np.mean([c['rmse_k']**2 for c in subset])))
            old_rmse = float(np.sqrt(np.mean([c['uniform_continuum_rmse_k']**2 for c in subset])))
            improved = sum(c['rmse_k'] < c['uniform_continuum_rmse_k'] for c in subset)
            summary[role+'_'+domain] = dict(case_count=len(subset), spatial_rmse_k=rmse,
                uniform_continuum_spatial_rmse_k=old_rmse, relative_reduction=1-rmse/old_rmse,
                improved_patterns=improved,
                boundary_improvement_screen=bool(rmse <= .8*old_rmse and improved >= 7) if role == 'held_out' and domain == 'all' else None)
    return dict(cases=cases, summary=summary, physical_model_qualified=False,
                scope='exploratory DC; copper storage and air boundary not validated')


def summarize(run, root):
    frozen = json.loads((run/'frozen-inputs.json').read_text())
    previous = json.loads((root/'ttc-spatial-dc-v1/report.json').read_text())
    power = np.array(list(patterns().values())).T
    report = dict(frozen, groups={}, complete=False)
    for group in ('heatsink', 'heatsink_with_fan'):
        continuum_path = run/(group+'-continuum.npz')
        if not continuum_path.exists():
            continue
        continuum = np.load(continuum_path)['resistance']
        levels = {}
        prior_contrasts = {}
        prior_raw, prior_corrected = {}, {}
        for level in range(4):
            folders = {m:run/group/('level-'+str(level))/m for m in ('U', 'C', 'P')}
            if not all((d/'receipt.json').exists() for d in folders.values()):
                break
            transfers = {}
            for m, d in folders.items():
                receipt = json.loads((d/'receipt.json').read_text())
                if digest(d/'transfer.npz') != receipt['transfer_sha256']:
                    raise ValueError('saved transfer digest mismatch')
                transfers[m] = np.load(d/'transfer.npz')['resistance']
            contrasts = {'C-U':transfers['C']-transfers['U'], 'P-C':transfers['P']-transfers['C']}
            entry = dict(contrasts={}, models={})
            for name, difference in contrasts.items():
                full = difference @ power
                spatial = projection(full)
                effect = float(abs(spatial).max())
                result = dict(max_full_effect_k=float(abs(full).max()), max_spatial_effect_k=effect)
                if name in prior_contrasts:
                    change = float(abs(spatial-prior_contrasts[name]).max())
                    result.update(last_spatial_refinement_change_k=change,
                                  relative_change=change/effect if effect > 0 else None,
                                  numerical_screen=bool(change < .02 and change < .1*effect))
                entry['contrasts'][name] = result
                prior_contrasts[name] = spatial
            for name, raw in transfers.items():
                corrected = continuum+(raw-transfers['U'])
                receipt = json.loads((folders[name]/'receipt.json').read_text())
                raw_prediction, corrected_prediction = raw @ power, corrected @ power
                model = dict(receipt=receipt,
                             raw=measured_diagnostic(raw, previous, root, group),
                             corrected=measured_diagnostic(corrected, previous, root, group),
                             max_uniform_fv_error_k=float(abs((transfers['U']-continuum) @ power).max()))
                if name in prior_raw:
                    model['last_raw_refinement_change_k'] = float(abs(raw_prediction-prior_raw[name]).max())
                    model['last_corrected_refinement_change_k'] = float(abs(corrected_prediction-prior_corrected[name]).max())
                prior_raw[name], prior_corrected[name] = raw_prediction, corrected_prediction
                entry['models'][name] = model
            levels[str(level)] = entry
        report['groups'][group] = dict(levels=levels)
    report['complete'] = len(report['groups']) == 2 and all(len(g['levels']) == 4 for g in report['groups'].values())
    write_json(run/'report.json', report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('results/physical-calibration'))
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--max-level', type=int, default=3, choices=range(4))
    args = ap.parse_args()
    code = [Path(__file__), Path('tools/validation/ttc_package.py'), Path('tools/validation/ttc_separable.py'),
            Path('tools/validation/ttc_spatial.py'), Path('tools/validation/ttc_spectral.py'),
            Path('tools/validation/ttc_geometry.py'), Path('tools/validation/measured_thermal.py'),
            Path('tools/validation/measured_sources.py'), Path('tools/measured-sources.lock.json'),
            Path('docs/ttc-package-boundary-plan.md'), Path('tools/ttc-upstream.lock.json'),
            Path('tools/ttc-package-boundary.lock.json')]
    hashes = {str(p):digest(p) for p in code}
    verify(args.root)
    geometry = extract(args.root/'ttc-origin')
    boundary = source_boundary(args.root/'ttc-origin')
    previous_path = args.root/'ttc-spatial-dc-v1/report.json'
    if args.resume:
        frozen = json.loads((args.output/'frozen-inputs.json').read_text())
        if frozen['code_sha256'] != hashes or frozen['prior_dc_report_sha256'] != digest(previous_path):
            raise ValueError('resume refused: frozen code/input changed')
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        frozen = dict(git=git_revision(Path('.')), code_sha256=hashes, geometry=geometry, boundary=boundary,
                      prior_dc_report_sha256=digest(previous_path), planned_levels=list(range(4)),
                      physical_model_qualified=False, no_new_fit=True, local_only=True)
        for p in code:
            shutil.copyfile(p, args.output/p.name)
        write_json(args.output/'frozen-inputs.json', frozen)
    for group in ('heatsink', 'heatsink_with_fan'):
        path = args.output/(group+'-continuum.npz')
        if not path.exists():
            resistance = continuum_transfer(geometry, group, 1., 1024)-1.
            np.savez_compressed(path, resistance=resistance)
    # Interleave groups at each refinement, preserving useful paired evidence.
    for level in range(args.max_level+1):
        for group in ('heatsink', 'heatsink_with_fan'):
            for model in ('U', 'C', 'P'):
                folder = args.output/group/('level-'+str(level))/model
                if (folder/'receipt.json').exists():
                    receipt = json.loads((folder/'receipt.json').read_text())
                    if digest(folder/'transfer.npz') != receipt['transfer_sha256']:
                        raise ValueError('completed result digest mismatch')
                    print('verified resume', group, level, model, flush=True)
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                print('assembling', group, level, model, flush=True)
                g, loss, b, h, assembly, audit = build(geometry, boundary, group, level, model)
                audit['slowest_time_constant_lower_bound_s'] = audit['total_capacity_j_per_k']/audit['total_boundary_conductance_w_per_k']
                write_json(folder/'assembly.json', audit)
                print('nodes', audit['node_count'], 'nnz', audit['nonzeros'], flush=True)
                def progress(record):
                    write_json(folder/'progress.json', record)
                    print(group, level, model, 'source', record['channel'], 'iters', record['iterations'],
                          'seconds', round(record['seconds'], 3), flush=True)
                resistance, solver = solve(g, loss, b, h, assembly, progress=progress)
                if model == 'U':
                    factor = 2**level
                    reference, _ = fv_transfer(geometry, group, 1., active_cells=factor,
                        bulk_cells=2*factor, pad_cells=2*factor, xy_edges=audit['die_xy_edges_m'])
                    discrepancy = float(abs((resistance-reference+1.) @ np.array(list(patterns().values())).T).max())
                    audit['same_mesh_separable_max_sensor_difference_k'] = discrepancy
                    if discrepancy > 1e-6:
                        raise ValueError('same-mesh independent U solve failed')
                np.savez_compressed(folder/'transfer.npz', resistance=resistance)
                write_json(folder/'receipt.json', dict(assembly=audit, solver=solver,
                    transfer_sha256=digest(folder/'transfer.npz'), physical_model_qualified=False))
                del g, loss, b, h, assembly
                gc.collect()
                summarize(args.output, args.root)
    report = summarize(args.output, args.root)
    print('planned sequence complete', report['complete'], flush=True)


if __name__ == '__main__':
    main()
