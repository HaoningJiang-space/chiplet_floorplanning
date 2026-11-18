"""Test power and peak-temperature bounds from a region's isothermal conductance."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from scipy.sparse import csc_matrix

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import (
    assemble_package, checked_solution, rectangle_slice, require_heat_path, solve_spd,
)
from chiplet_floorplanning.placement import Layout, Problem, thermal_case_data
from chiplet_floorplanning.power import rasterize
from headroom_selection import conditions, length_m


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def source_map(case, layer, node_count):
    """Columns deposit 1 W uniformly over one die, exactly conserving watts."""
    ids, owners, weights = [], [], []
    for i, die in enumerate(case.dies):
        bounds = rectangle_slice(case, die.bounds)
        nodes = layer[bounds].ravel()
        area = case.mesh.areas_mm2[bounds].ravel()
        assert (nodes >= 0).all() and area.min() > 0
        ids.extend(nodes)
        owners.extend([i] * len(nodes))
        weights.extend(area / area.sum())
    assert len(ids) == len(set(ids))
    return csc_matrix((weights, (ids, owners)), shape=(node_count, len(case.dies)))


def regions(layout):
    n = len(layout.centre_um)
    dist = np.linalg.norm(layout.centre_um[:, None] - layout.centre_um[None, :], axis=2)
    np.fill_diagonal(dist, np.inf)
    pairs = {tuple(sorted((i, int(j)))) for i, j in enumerate(dist.argmin(axis=1))}
    return [(i,) for i in range(n)] + sorted(pairs) + [tuple(range(n))]


def probe(matrix, sink, source_ids):
    """Ground ambient and clamp all selected source cells at +1 K."""
    free = np.ones(matrix.shape[0], dtype=bool)
    free[source_ids] = False
    u = np.zeros(matrix.shape[0])
    u[source_ids] = 1
    forcing = -(matrix @ u)[free]
    u[free] = solve_spd(matrix[free][:, free], forcing)
    flux = (matrix @ u)[source_ids]
    conductance = float(flux.sum())
    assert u.min() >= -1e-9 and u.max() <= 1 + 1e-9 and flux.min() >= 0
    assert conductance > 0 and abs(sink @ u - conductance) < 1e-7
    return conductance, u, flux


def run_layout(job):
    problem, layout, gap, archive_id, boundary, resolution = job
    variants = conditions(problem)
    p = variants[boundary]
    data = thermal_case_data(p, layout, gap, resolution)
    case = parse_case(data)
    assert [die.id for die in case.dies] == list(p.names)
    power, _ = rasterize(case)
    matrix, nominal_rhs, sink, _, ids, z = assemble_package(case, power)
    require_heat_path(matrix, sink)
    deposit = source_map(case, ids[z], matrix.shape[0])
    assert np.max(abs(deposit @ p.power_w - nominal_rhs)) < 1e-8
    all_sources = deposit.indices
    loads = {'nominal': p.power_w, 'shifted_power': variants['shifted_power'].power_w}
    fields, cases = {}, {}
    max_balance = 0.0

    def forward(rhs):
        nonlocal max_balance
        theta = solve_spd(matrix, rhs)
        _, removed = checked_solution(matrix, rhs, sink, theta)
        max_balance = max(max_balance, abs(removed - rhs.sum()))
        assert abs(theta.max() - theta[all_sources].max()) < 1e-7
        return theta

    for name, watts in loads.items():
        fields[name] = forward(deposit @ watts)
        cases[name] = dict(total_w=float(watts.sum()), peak_rise_k=float(fields[name].max()))
    region_rows, best = [], {}
    max_identity_error = 0.0
    for region in regions(layout):
        idx = np.concatenate([deposit.indices[deposit.indptr[i]:deposit.indptr[i+1]] for i in region])
        conductance, u, flux = probe(matrix, sink, idx)
        influences = np.asarray(deposit.T @ u)
        samples = {}
        for name, watts in loads.items():
            local_w = float(watts[list(region)].sum())
            local_bound = local_w / conductance
            weighted_bound = float(influences @ watts) / conductance
            measured = float(flux @ fields[name][idx]) / conductance
            max_identity_error = max(max_identity_error, abs(measured-weighted_bound))
            assert local_bound <= weighted_bound + 1e-7
            assert weighted_bound <= fields[name][idx].max() + 1e-7
            samples[name] = dict(local_w=local_w, local_bound_k=local_bound,
                                 weighted_bound_k=weighted_bound)
            if name not in best or weighted_bound > best[name][0]:
                best[name] = (weighted_bound, region, idx, flux, conductance, influences)
        region_rows.append(dict(dies=region, conductance_w_k=conductance, samples=samples))
        if len(region) == p.count:
            ideal = np.zeros_like(nominal_rhs)
            ideal[idx] = flux * (p.power_w.sum()/conductance)
            theta = forward(ideal)
            ideal_error = float(abs(theta[idx] - p.power_w.sum()/conductance).max())
            assert ideal_error < 1e-6

    assert max_identity_error < 1e-6
    singles = {r['dies'][0]: r['conductance_w_k'] for r in region_rows if len(r['dies']) == 1}
    for row in region_rows:
        if len(row['dies']) == 2:
            separate = sum(singles[i] for i in row['dies'])
            row['shared_fraction'] = 1 - row['conductance_w_k']/separate
            assert -1e-9 <= row['shared_fraction'] <= 1

    for name, watts in loads.items():
        weighted_bound, region, idx, flux, conductance, influences = best[name]
        # Several cells can have unit influence by construction. Break numerical ties by source order.
        rank = influences.round(11)
        donor = int(np.argmax(np.where(watts >= 1, rank, -np.inf)))
        recipient = int(np.argmin(np.where(np.arange(len(watts)) != donor, rank, np.inf)))
        assert donor != recipient and watts[donor] >= 1
        moved = watts.copy()
        moved[donor] -= 1
        moved[recipient] += 1
        prediction = float((influences[recipient] - influences[donor])/conductance)
        updated = forward(deposit @ moved)
        observed = float(flux @ (updated[idx] - fields[name][idx]))/conductance
        assert abs(prediction - observed) < 1e-6
        cases[name]['transfer'] = dict(region=region, donor=donor, recipient=recipient,
                                      predicted_region_delta_k=prediction, region_delta_k=observed,
                                      peak_delta_k=float(updated.max() - fields[name].max()))
    return dict(case=problem.name, archive_id=archive_id, resolution=resolution, boundary=boundary,
                ambient_c=data['thermal']['ambient_c'], length_m=length_m(p, layout),
                names=p.names, regimes=cases, regions=region_rows,
                max_identity_error_k=max_identity_error, equal_source_error_k=ideal_error,
                max_balance_error_w=max_balance, forward_solves=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=12)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    evidence = Path(__file__).resolve().parents[1] / 'docs/evidence/headroom-selection-v1.json'
    driver_sha = digest(Path(__file__))
    with ProcessPoolExecutor(args.workers) as pool:
        pending = {}
        for ref in json.loads(evidence.read_text())['records']:
            name = ref['case']
            if name.startswith('Case'):
                source = args.data / 'physical-calibration/atplace-import-v1' / (name+'.json')
                archive = args.data / 'rs-grb-v4' / name.lower()
            else:
                source = args.data / 'industrial-v1/cases' / (name+'.json')
                archive = args.data / 'industrial-v1/runs' / name
            assert digest(source) == ref['case_sha256']
            assert digest(archive/'summary.json') == ref['summary_sha256']
            problem = Problem.from_imported(json.loads(source.read_text()))
            with np.load(archive/'layouts.npz') as z:
                centres, turns = z['centre_um'], z['rotation_deg']
            for j, group in enumerate(ref['groups']):
                idx = group['archive_id']
                layout = Layout(centres[idx], turns[idx])
                levels = [('nominal', 64), ('stronger_sink', 64)]
                if j == 0:
                    levels.append(('nominal', 96))
                for boundary, res in levels:
                    job = (problem, layout, ref['gap_um'], idx, boundary, res)
                    handle = pool.submit(run_layout, job)
                    pending[handle] = (name, idx, boundary, res, ref)
        for handle in as_completed(pending):
            name, idx, boundary, res, ref = pending[handle]
            row = handle.result()
            row.update(case=name, driver_sha256=driver_sha, case_sha256=ref['case_sha256'],
                       archive_summary_sha256=ref['summary_sha256'])
            dest = args.output / f'{name}-{idx}-{boundary}-{res}.json'
            dest.write_text(json.dumps(row, allow_nan=False)+'\n')
            print(dest.name, len(row['regions']), flush=True)


if __name__ == '__main__':
    main()
