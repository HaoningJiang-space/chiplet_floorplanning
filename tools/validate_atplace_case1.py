"""One bounded source-pin/geometry/thermal acceptance; no optimizer comparison."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

from atplace_pin_geometry import UniformDiePinEvaluator
from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import assemble_package
from chiplet_floorplanning.power import rasterize
from solve_tap_fv_hits import run


def source_hash(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def fixed_layouts():
    positions = [('CPU1_0', 7000, 29000), ('GPU_0', 10000, 10000),
                 ('GPU_1', 30000, 10000), ('HBM_0', 19000, 29000),
                 ('HBM_1', 29000, 29000), ('HBM_2', 38000, 29000)]
    base = [dict(chiplet=name, centre_x_um=x, centre_y_um=y, rotation_deg=0)
            for name, x, y in positions]
    rotation, movement = deepcopy(base), deepcopy(base)
    rotation[0]['rotation_deg'] = 180
    movement[1].update(centre_x_um=11000, centre_y_um=11000)
    return [('base', base), ('cpu_rotation_180', rotation), ('gpu_translation_1mm_xy', movement)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--hits', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    source = json.loads(raw)
    receipt = json.loads(Path('docs/evidence/atplace-import.json').read_text())
    expected = next(c for c in receipt['cases'] if c['case'] == 'Case1')
    if source['name'] != 'Case1' or hashlib.sha256(raw).hexdigest() != expected['imported_sha256']:
        raise ValueError('Expected the previously verified Case1 import')
    args.output.mkdir(parents=True, exist_ok=False)
    write = lambda name, value: (args.output/name).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    plan = dict(scope='three preselected acceptance layouts, not optimization or independent physical calibration',
                source_commit=source['source_commit'], imported_sha256=expected['imported_sha256'],
                source_sha256=source['source_sha256'], source_case='Case1', gap_um=1000,
                gap_provenance='declared research clearance, not supplied by the three source input files',
                grid='continuous centres accepted; this fixture uses integer micrometres',
                package='TAP-family FV materials; source 42x42 mm carrier; fixed 100/200 mm spreader/sink',
                heat_boundary='ambient 45 C; top h=2777.7777778 W/(m2 K); other external faces adiabatic',
                power='uniform full source die, fixed source power; no extra bump ring or leakage feedback',
                metric='total two-pin Manhattan lower bound in metres, unweighted source-net multiplicity',
                electrical_timing='not connected; undirected source B pins do not define clock/data direction',
                cache='private uniform-die thermal cache by physical bounds; recompute pin objective for every full-orientation layout',
                code_base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                code_version='listed source hashes bind the executed worktree, including new files after the base commit',
                source_hashes={p: source_hash(p) for p in ('tools/atplace_pin_geometry.py',
                    'tools/validate_atplace_case1.py', 'tools/solve_tap_fv_hits.py',
                    'src/chiplet_floorplanning/model.py', 'src/chiplet_floorplanning/package.py',
                    'src/chiplet_floorplanning/mesh.py', 'src/chiplet_floorplanning/power.py')},
                hits_commit=subprocess.check_output(['git', '-C', str(args.hits), 'rev-parse', 'HEAD'], text=True).strip(),
                layouts=[dict(name=name, placements=p) for name, p in fixed_layouts()])
    write('plan.json', plan)
    records = []
    baseline = None
    evaluator = UniformDiePinEvaluator(source, plan['gap_um'], lambda data: run(parse_case(data), args.hits))
    layout_keys = set()
    for layout in plan['layouts']:
        name, placements = layout['name'], layout['placements']
        evaluated = evaluator.evaluate(placements)
        layout_keys.add(evaluated['layout_key'])
        metric, data = evaluated['metric'], evaluated['case_data']
        case = parse_case(data)
        # Independently transform the source pins through the production Die API.
        by_name = {d.id: d for d in case.dies}
        carrier_offset_mm = [(200-source[key]/1000)/2
                             for key in ('interposer_width_um', 'interposer_height_um')]
        max_endpoint_error = 0.
        total = 0.
        for net, row in zip(source['nets'], metric['nets']):
            points = []
            for i, pin in enumerate(net['pins']):
                die = by_name[pin['chiplet']]
                point = die.point(*die.ports[f"n{net['id']}_{i}"])
                points.append(point)
                expected_point = [offset+float(v)/1000
                                  for offset, v in zip(carrier_offset_mm, row['endpoints_um_decimal'][i])]
                max_endpoint_error = max(max_endpoint_error, *(abs(a-b) for a, b in zip(point, expected_point)))
            total += sum(abs(a-b) for a, b in zip(*points))
        if max_endpoint_error > 1e-9 or abs(total-metric['total_pin_manhattan_mm']) > 1e-7:
            raise ValueError('Source centre-offset and package lower-left transformations disagree')
        write(name+'-case.json', data)
        write(name+'-pins.json', metric)
        thermal_raw, field, matrix, rhs = evaluated['thermal_result']
        thermal = dict(thermal_raw)
        thermal['scope'] = 'declared common FV model on ATPlace Case1; not native ATPlace or independently calibrated'
        if not thermal['numerical_admission_passed']:
            raise ValueError('Thermal numerical acceptance failed')
        item = dict(name=name, placements=placements,
                    thermal_cache_hit=evaluated['thermal_cache_hit'],
                    metric={k: v for k, v in metric.items() if k != 'nets'},
                    registered_pin_count=sum(len(d.ports) for d in case.dies),
                    max_endpoint_transform_error_mm=max_endpoint_error,
                    production_transform_total_length_mm=total,
                    thermal={k: v for k, v in thermal.items() if k != 'power_mapping'},
                    case_sha256=source_hash(args.output/(name+'-case.json')),
                    pins_sha256=source_hash(args.output/(name+'-pins.json')))
        if baseline is None:
            baseline = matrix, rhs, field
        elif name == 'cpu_rotation_180':
            # Check the rotation's actual operator, not merely its cached label.
            rotated_a, rotated_b, *_ = assemble_package(case, rasterize(case)[0])
            item['rotation_control'] = dict(operator_identical=(rotated_a != baseline[0]).nnz == 0,
                                           source_identical=bool(np.array_equal(rotated_b, baseline[1])),
                                           max_cached_field_difference_k=float(np.max(np.abs(field-baseline[2]))))
            if not (item['rotation_control']['operator_identical'] and item['rotation_control']['source_identical']):
                raise ValueError('Uniform square die rotation unexpectedly changed the thermal problem')
        records.append(item)
        write(name+'-result.json', item)
        print(name, metric['total_pin_manhattan_m'], thermal['peak_power_layer_c'], flush=True)
    rotation_changes_pins = records[0]['metric']['total_pin_manhattan_mm'] != records[1]['metric']['total_pin_manhattan_mm']
    movement_changes_pins = records[0]['metric']['total_pin_manhattan_mm'] != records[2]['metric']['total_pin_manhattan_mm']
    # Movement temperature response is reported, not forced to have a favorable sign.
    if not rotation_changes_pins or not movement_changes_pins:
        raise ValueError('The preselected diagnostic did not distinguish the pin objective')
    result = dict(status='complete_case1_pin_geometry_thermal_acceptance', plan=plan, records=records,
                  rotation_changes_pin_objective=rotation_changes_pins,
                  movement_changes_pin_objective=movement_changes_pins,
                  movement_peak_change_k=records[2]['thermal']['peak_power_layer_c']-records[0]['thermal']['peak_power_layer_c'],
                  full_layout_states=len(layout_keys),
                  full_thermal_solves=evaluator.solve_count, thermal_cache_hits=evaluator.cache_hits,
                  physical_calibrated=False, timing_closed=False,
                  scope='source pin geometry and declared thermal evaluator connected; no optimizer, routed wirelength, RC or timing claim')
    write('result.json', result)


if __name__ == '__main__':
    main()
