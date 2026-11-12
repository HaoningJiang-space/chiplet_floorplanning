"""Local fixed-parameter package transients with separate reduction controls."""

import argparse
import gc
import json
from pathlib import Path
import shutil

import numpy as np

from calibrate_measured_transient import case_data
from validation.measured_sources import digest, verify
from validation.measured_thermal import patterns
from validation.sources import git_revision, write_json
from validation.ttc_geometry import extract
from validation.ttc_observation import raw_metrics
from validation.ttc_package import source_boundary, build
from validation.ttc_reduction import SHIFTS, snapshot_bank, project, frequency_reference, backward_euler_pulse


def contrast(values):
    return values-values.mean(axis=-1, keepdims=True)


def pulse(reduced, power):
    sensors, bodies, removed = [], [], []
    for p in power.T:
        trace = np.r_[np.tile(p, (5, 1)), np.full((5, 16), .2)]
        initial = (np.full(16, .2) @ reduced.inputs)/reduced.rates
        y, _, audit = reduced.run(trace, initial)
        sensors.append(y)
        energy = initial @ reduced.body_storage+np.cumsum(audit['body_storage_rate_w']*.1, axis=0)
        bodies.append(energy/reduced.body_capacities)
        removed.append(np.cumsum(audit['boundary_loss_w']*.1))
    return dict(sensors=np.moveaxis(sensors, 0, -1), body_means=np.moveaxis(bodies, 0, -1),
                cumulative_boundary_heat_j=np.array(removed).T)


def physical_flux_check(reduced, assembly):
    w = reduced.reconstruction
    names = {block.name:i for i, block in enumerate(assembly.blocks)}
    flux = np.zeros_like(reduced.body_flow)
    owner = np.empty(len(w), dtype=int)
    for i, block in enumerate(assembly.blocks):
        owner[block.ids.ravel()] = i
    for edge in assembly.interfaces:
        a, b = edge['a'], edge['b']
        value = edge['g'] @ (w[a]-w[b])
        lower, upper = edge['name'].split('->')
        flux[:, names[lower]] += value
        flux[:, names[upper]] -= value
    for ids, g in assembly.anchors:
        if np.unique(owner[ids]).size != 1:
            raise ValueError('boundary anchor unexpectedly spans bodies')
        flux[:, owner[ids[0]]] += g @ w[ids]
    return float(abs(flux-reduced.body_flow).max())


def controls(g, c, b, h, loss, groups, assembly, reductions, folder):
    power = np.array(list(patterns().values())).T
    result = dict(orders={}, backward_euler={})
    omega_values = [.003, .03, .3, 3., 30., 300.]
    frequency_errors = {str(i):[] for i in range(3)}
    for omega in omega_values:
        print('full frequency reference', omega, flush=True)
        reference = frequency_reference(g, c, b, h, [omega])[omega]
        for i, reduced in enumerate(reductions):
            frequency_errors[str(i)].append(float(abs((reduced.frequency(omega)-reference) @ power).max()))
    saved = {}
    times = np.r_[0., np.geomspace(1e-6, 2000., 160)]
    for i, reduced in enumerate(reductions):
        step = reduced.steps(power, times)
        negative = max(0., -float(step.min()))
        nonmonotone = max(0., -float(np.diff(step, axis=0).min()))
        result['orders'][str(i)] = dict(audit=reduced.audit,
            withheld_frequency_omega_per_s=omega_values, withheld_frequency_max_error_k=frequency_errors[str(i)],
            max_reconstructed_interface_flux_coefficient_error=physical_flux_check(reduced, assembly),
            minimum_step_temperature_k=float(step.min()), max_step_decrease_k=nonmonotone,
            step_positivity_monotonicity_screen=bool(max(negative, nonmonotone) < 1e-8))
        values = pulse(reduced, power)
        for key, value in values.items():
            saved['rom_'+str(i)+'_'+key] = value
    bes = []
    for dt in (.005, .0025, .00125):
        print('full backward Euler reference', dt, flush=True)
        be = backward_euler_pulse(g, c, b, h, power, dt, groups, loss)
        bes.append(be)
        result['backward_euler'][str(dt)] = dict(max_numerical_heat_balance_error_j=be['max_numerical_heat_balance_error_j'])
        for key in ('sensors', 'body_means', 'cumulative_boundary_heat_j'):
            saved['be_'+str(dt)+'_'+key] = be[key]
    extrapolated = {}
    for key in ('sensors', 'body_means'):
        first, second = 2*bes[1][key]-bes[0][key], 2*bes[2][key]-bes[1][key]
        extrapolated[key] = second
        result['backward_euler'][key+'_extrapolation_change_k'] = float(abs(second-first).max())
        for i in range(3):
            result['orders'][str(i)][key+'_max_error_to_be_extrapolate_k'] = float(abs(saved['rom_'+str(i)+'_'+key]-second).max())
        saved['richardson_'+key] = second
    for entry in result['orders'].values():
        entry['fixed_mesh_numerical_screen'] = bool(
            max(entry['withheld_frequency_max_error_k']) < .01 and
            entry['step_positivity_monotonicity_screen'] and
            max(result['backward_euler'][key+'_extrapolation_change_k'] for key in ('sensors', 'body_means')) < .01 and
            max(entry[key+'_max_error_to_be_extrapolate_k'] for key in ('sensors', 'body_means')) < .02)
    np.savez_compressed(folder/'numerical-controls.npz', **saved)
    write_json(folder/'numerical-controls.json', result)
    return result


def metrics(prediction, measured):
    error = prediction-measured
    common = error.mean(axis=1)
    spatial = error-common[:, None]
    return dict(raw=raw_metrics(error), common_rmse_k=float(np.sqrt(np.mean(common**2))),
                spatial_rmse_k=float(np.sqrt(np.mean(spatial**2))))


def evaluate_cases(reductions, cases, prior_dc, resistance, folder):
    result = []
    for case in cases:
        record = next(r for r in prior_dc['cases'] if r['name'] == case['name'])
        start = record['start_raw_row']-case['start_index']
        end = record['end_raw_row_exclusive']-case['start_index']
        power = case['power_w']
        measured = case['temperature_rise_k']
        mean_power = power[start:end].mean(axis=0)
        steady = resistance @ mean_power
        entry = dict(name=case['name'], role=case['role'], source_power_domain=bool(mean_power.sum() < 40),
                     first_raw_index=case['start_index'], sample_count=len(power), variants={})
        saved = dict(measured_c=measured+case['ambient_c'], power_w=power)
        for uniform, name in ((False, 'conditional_gradient'), (True, 'uniform')):
            orders = []
            previous = None
            for index, reduced in enumerate(reductions):
                initial = reduced.initial(power, measured[0], uniform)
                prediction, ledger, physics = reduced.run(power, initial)
                item = dict(order=index, scores=metrics(prediction, measured), heat_ledger=ledger)
                if previous is not None:
                    item['max_change_from_previous_order_k'] = float(abs(prediction-previous).max())
                previous = prediction
                mean_prediction = prediction[start:end].mean(axis=1)
                mean_measured = measured[start:end].mean(axis=1)
                dynamic_difference = contrast(prediction[start:end]).mean(axis=0)
                static_difference = contrast(steady)
                body_storage = physics['body_storage_rate_w'][start:end].mean(axis=0)
                item['dc_window'] = dict(
                    measured_sensor_mean_slope_k_per_s=float((mean_measured[45:].mean()-mean_measured[:45].mean())/4.5),
                    predicted_sensor_mean_slope_k_per_s=float((mean_prediction[45:].mean()-mean_prediction[:45].mean())/4.5),
                    dynamic_spatial_rmse_k=float(np.sqrt(np.mean((dynamic_difference-np.array(record['measured_sensor_difference_k']))**2))),
                    static_spatial_rmse_k=float(np.sqrt(np.mean((static_difference-np.array(record['measured_sensor_difference_k']))**2))),
                    max_dynamic_minus_static_spatial_k=float(abs(dynamic_difference-static_difference).max()),
                    dynamic_sensor_difference_k=dynamic_difference.tolist(), static_sensor_difference_k=static_difference.tolist(),
                    power_w=float(mean_power.sum()), storage_rate_w=float(body_storage.sum()),
                    die_storage_w=float(body_storage[0]), pad_storage_w=float(body_storage[1]),
                    base_storage_w=float(body_storage[2]), fins_storage_w=float(body_storage[3:].sum()),
                    boundary_heat_loss_w=float(physics['boundary_loss_w'][start:end].mean()))
                orders.append(item)
                saved[name+'_order_'+str(index)+'_c'] = prediction+case['ambient_c']
                if index == 2:
                    saved[name+'_body_storage_w'] = physics['body_storage_rate_w']
                    saved[name+'_boundary_loss_w'] = physics['boundary_loss_w']
            entry['variants'][name] = orders
        wave = folder/(case['name']+'.npz')
        np.savez_compressed(wave, **saved)
        entry['waveform_sha256'] = digest(wave)
        result.append(entry)
        write_json(folder/'case-progress.json', result)
        print('measured case', case['name'], 'completed', flush=True)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path('results/physical-calibration'))
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--max-level', type=int, choices=(0, 1), default=1)
    args = ap.parse_args()
    verify(args.root)
    geometry = extract(args.root/'ttc-origin')
    boundary = source_boundary(args.root/'ttc-origin')
    admission_path = args.root/'thermal-fit-v2/report.json'
    dc_path = args.root/'ttc-spatial-dc-v1/report.json'
    admission, previous_dc = json.loads(admission_path.read_text()), json.loads(dc_path.read_text())
    paths = [Path(__file__), Path('tools/validation/ttc_reduction.py'), Path('tools/validation/ttc_package.py'),
             Path('tools/validation/ttc_separable.py'), Path('tools/validation/ttc_spatial.py'),
             Path('tools/validation/ttc_geometry.py'), Path('tools/validation/measured_thermal.py'),
             Path('tools/calibrate_measured_transient.py'), Path('docs/ttc-package-transient-plan.md'),
             Path('tools/ttc-package-boundary.lock.json'), Path('tools/ttc-upstream.lock.json'), Path('tools/measured-sources.lock.json')]
    hashes = {str(p):digest(p) for p in paths}
    dependencies = {str(p):digest(p) for p in (admission_path, dc_path)}
    if args.resume:
        frozen = json.loads((args.output/'frozen-inputs.json').read_text())
        if frozen['code_sha256'] != hashes or frozen['dependency_sha256'] != dependencies:
            raise ValueError('resume refused: code/input hashes changed')
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        frozen = dict(git=git_revision(Path('.')), code_sha256=hashes, dependency_sha256=dependencies,
                      geometry=geometry, boundary=boundary, shifts_per_s=SHIFTS,
                      no_new_fit=True, physical_model_qualified=False, planned_levels=[0, 1])
        for p in paths:
            shutil.copyfile(p, args.output/p.name)
        write_json(args.output/'frozen-inputs.json', frozen)
    report_path = args.output/'report.json'
    report = json.loads(report_path.read_text()) if args.resume and report_path.exists() else dict(frozen, completed={})
    cases = {group:[case_data(args.root, group, record) for record in data['cases']] for group, data in admission['groups'].items()}
    for level in range(args.max_level+1):
        for group in ('heatsink', 'heatsink_with_fan'):
            for model in ('C', 'P'):
                key = group+'_'+model+'_level'+str(level)
                folder = args.output/key
                if (folder/'receipt.json').exists():
                    receipt = json.loads((folder/'receipt.json').read_text())
                    for case in receipt['cases']:
                        if digest(folder/(case['name']+'.npz')) != case['waveform_sha256']:
                            raise ValueError('saved waveform hash mismatch')
                    report['completed'][key] = receipt
                    print('verified resume', key, flush=True)
                    continue
                folder.mkdir(parents=True, exist_ok=True)
                print('build', key, flush=True)
                g, loss, b, h, assembly, geometry_audit = build(geometry, boundary, group, level, model)
                c = np.concatenate([block.capacity.ravel() for block in assembly.blocks])
                groups = [block.ids.ravel() for block in assembly.blocks]
                write_json(folder/'geometry.json', geometry_audit)
                def progress(record):
                    write_json(folder/'snapshot-progress.json', record)
                    print('snapshot', record, flush=True)
                bank, snapshot_audit = snapshot_bank(g, c, b, progress=progress)
                reductions = [project(g, c, b, h, loss, groups, bank, shifts) for shifts in SHIFTS]
                for i, reduced in enumerate(reductions):
                    print('projection', i, reduced.audit, flush=True)
                resistance = np.asarray(h @ bank[0.])
                del bank
                numerical = controls(g, c, b, h, loss, groups, assembly, reductions, folder)
                results = evaluate_cases(reductions, cases[group], previous_dc['groups'][group], resistance, folder)
                receipt = dict(group=group, model=model, level=level, geometry=geometry_audit,
                               snapshots=snapshot_audit, numerical_controls=numerical, cases=results,
                               max_native_trace_order_change_k=max(v[-1]['max_change_from_previous_order_k'] for r in results for v in r['variants'].values()),
                               physical_model_qualified=False)
                receipt['fixed_mesh_reduction_screen'] = bool(numerical['orders']['2']['fixed_mesh_numerical_screen'] and
                    receipt['max_native_trace_order_change_k'] < .01 and all(v[-1]['heat_ledger']['numerical_heat_balance_screen'] for r in results for v in r['variants'].values()))
                write_json(folder/'receipt.json', receipt)
                report['completed'][key] = receipt
                report['complete'] = len(report['completed']) == 8
                write_json(report_path, report)
                del g, loss, b, h, assembly, reductions, c
                gc.collect()
    print('completed models', len(report['completed']), flush=True)


if __name__ == '__main__':
    main()
