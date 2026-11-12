"""Bounded, preselected local layout sensitivity and linear source decomposition."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import time
import numpy as np
from build_tap_algorithm_oracle import centre_span
from build_tap_ihp_endpoints import source_bytes
from freeze_tap_geometry import candidates, separated, verify
from prepare_tap_fv import make_case
from solve_tap_fv_hits import run
from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import assemble_package, material_grids
from chiplet_floorplanning.power import rasterize


def thermal_key(placement):
    return tuple((p['id'], p['centre_x_um'], p['centre_y_um'], p['rotation_deg'] % 180)
                 for p in sorted(placement, key=lambda p: p['id']))


def sample_layouts(domain, count, seed):
    """Sequential legal construction, NOT uniform over joint legal layouts."""
    rng = random.Random(seed)
    choices = {c['id']: list(candidates(domain, c)) for c in domain['chiplets']}
    seen, layouts = set(), []
    for attempt in range(10000):
        order = list(choices)
        rng.shuffle(order)
        placement, bounds = [], []
        for i in order:
            legal = [(p, b) for p, b in choices[i]
                     if all(separated(b, other, domain['minimum_gap_um']) for other in bounds)]
            if not legal:
                break
            p, b = rng.choice(legal)
            placement.append(p)
            bounds.append(b)
        else:
            placement.sort(key=lambda p: p['id'])
            verify(domain, placement)
            key = thermal_key(placement)
            if key not in seen:
                seen.add(key)
                layouts.append(placement)
            if len(layouts) == count:
                return layouts, attempt + 1
    raise ValueError('Sampling exhausted; unknown, not geometric infeasibility')


def freeze_plan(path):
    geometry = source_bytes('docs/evidence/tap-geometry-domains.json')
    oracle = source_bytes('docs/evidence/tap-algorithm-oracle.json')
    rows = json.loads(oracle)['rows']
    ordered = sorted(rows, key=lambda r: (r['peak_c'], r['class_index']))
    plan = dict(seed=20261112, samples_per_case=20,
                geometry_sha256=hashlib.sha256(geometry).hexdigest(),
                oracle_sha256=hashlib.sha256(oracle).hexdigest(),
                sampling='random chip order and uniform legal next-chip candidate; biased joint distribution',
                cases=[], decomposition_classes=[ordered[0], ordered[len(ordered)//2], ordered[-1]])
    for entry in json.loads(geometry)['cases']:
        domain = entry['domain']
        placements, attempts = sample_layouts(domain, 20, plan['seed'])
        plan['cases'].append(dict(domain=domain, placements=placements, construction_attempts=attempts))
    with path.open('x', encoding='utf-8') as f:
        json.dump(plan, f, indent=2)
        f.write('\n')


def source_case(data, source_id):
    result = copy.deepcopy(data)
    for chip in result['chiplets']:
        if chip['id'] != source_id:
            for block in chip['blocks']:
                block['power_w'] = 0
    return parse_case(result)


def decompose(domain, row, hits):
    data = make_case(domain, row['placement'])
    case = parse_case(data)
    summary, total, matrix, rhs = run(case, hits)
    if not summary['numerical_admission_passed']:
        raise ValueError('Total solve failed')
    power, _ = rasterize(case)
    _, _, _, nodes, ids, power_z = assemble_package(case, power)
    active = ids[power_z][ids[power_z] >= 0]
    hotspot = int(active[np.argmax(total[active])])
    z, y, x = nodes[hotspot]
    owner = int(material_grids(case)[0][y, x])
    accumulated = np.zeros_like(total)
    accumulated_rhs = np.zeros_like(rhs)
    contributions = []
    for chip in case.dies:
        single = source_case(data, chip.id)
        result, field, a, b = run(single, hits)
        if a.shape != matrix.shape or (a != matrix).nnz:
            raise ValueError('Source isolation changed thermal operator')
        if not result['numerical_admission_passed']:
            raise ValueError('Source solve failed')
        accumulated += field
        accumulated_rhs += b
        contributions.append(dict(source=chip.id, power_w=result['source_power_w'],
                                  hotspot_contribution_k=float(field[hotspot]),
                                  thermal=result))
    error = float(np.max(np.abs(accumulated-total)))
    rhs_error = float(np.max(np.abs(accumulated_rhs-rhs)))
    if error > 1e-6 or rhs_error > 1e-10:
        raise ValueError('Linear source decomposition failed')
    owner_id = case.dies[owner].id if owner >= 0 else None
    own = next((r['hotspot_contribution_k'] for r in contributions if r['source'] == owner_id), None)
    return dict(class_index=row['class_index'], placement=row['placement'], thermal=summary,
                hotspot=dict(node=hotspot, layer=z, row=y, column=x, owner=owner_id),
                self_rise_k=own, other_sources_rise_k=float(total[hotspot]-own) if own is not None else None,
                field_superposition_error_k=error, rhs_superposition_error_w=rhs_error,
                original_oracle_peak_difference_k=summary['peak_power_layer_c']-row['peak_c'],
                contributions=contributions)


def evaluate(plan_path, output, hits):
    raw = source_bytes(plan_path)
    plan = json.loads(raw)
    output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    result = dict(status='running', plan_sha256=hashlib.sha256(raw).hexdigest(),
                  cases=[], decomposition=[], physical_calibrated=False,
                  scope='preselected samples, not global extrema or uniform-distribution estimates')
    for entry in plan['cases']:
        domain = entry['domain']
        rows = []
        for i, placement in enumerate(entry['placements']):
            summary, _, _, _ = run(parse_case(make_case(domain, placement)), hits)
            row = dict(index=i, placement=placement, centre_span_mm=centre_span(domain, placement), thermal=summary)
            (output/f"{domain['name']}-{i:02d}.json").write_text(json.dumps(row, indent=2), encoding='utf-8')
            if not summary['numerical_admission_passed']:
                raise ValueError('Sample solve failed; no replacement sampling')
            rows.append(row)
            print(domain['name'], i, summary['peak_power_layer_c'], flush=True)
        peaks = [r['thermal']['peak_power_layer_c'] for r in rows]
        result['cases'].append(dict(case=domain['name'], rows=rows,
                                    min_peak_c=min(peaks), max_peak_c=max(peaks), sampled_span_k=max(peaks)-min(peaks)))
    domain = next(e['domain'] for e in plan['cases'] if e['domain']['name'] == 'ascend910')
    for row in plan['decomposition_classes']:
        record = decompose(domain, row, hits)
        (output/f"decomposition-{row['class_index']}.json").write_text(json.dumps(record, indent=2), encoding='utf-8')
        result['decomposition'].append(record)
        print('decomposition', row['class_index'], record['self_rise_k'], record['other_sources_rise_k'], flush=True)
    result.update(status='complete_bounded_diagnostic', elapsed_seconds=time.perf_counter()-start,
                  full_power_solves=63, single_source_solves=18)
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--hits', type=Path)
    args = parser.parse_args()
    if args.freeze:
        freeze_plan(args.plan)
    else:
        if args.output is None or args.hits is None:
            parser.error('--output and --hits required for evaluation')
        evaluate(args.plan, args.output, args.hits)
