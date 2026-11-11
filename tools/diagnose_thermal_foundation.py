"""Bounded thermal diagnostics; not junction-temperature or physical validation."""

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.cli import source_revision
from chiplet_floorplanning.model import load_case, parse_case
from chiplet_floorplanning.package import solve_package
from chiplet_floorplanning.power import rasterize


def solve(raw):
    case = parse_case(raw)
    power, _ = rasterize(case)
    temperature, summary = solve_package(case, power)
    return case, temperature, summary


def diagnose(raw):
    rows = []
    for xy_scale in (1, 2):
        for slices in (1, 2, 4, 8):
            refined = copy.deepcopy(raw)
            refined['grid']['nx'] *= xy_scale
            refined['grid']['ny'] *= xy_scale
            layers = []
            for layer in refined['thermal']['layers']:
                if layer['id'] == refined['thermal']['power_layer']:
                    layers.append(layer)
                    continue
                for index in range(slices):
                    part = copy.deepcopy(layer)
                    part['id'] = layer['id'] + '_z' + str(index)
                    part['thickness_mm'] /= slices
                    if index < slices - 1:
                        part.pop('contact_resistance_above_m2k_w', None)
                    layers.append(part)
            refined['thermal']['layers'] = layers
            _, _, summary = solve(refined)
            rows.append(dict(xy_scale=xy_scale, passive_z_slices=slices,
                             peak_c=summary['peak_c'], nodes=summary['node_count'],
                             energy_error_w=summary['energy_balance_error_w']))
    case, total, _ = solve(raw)
    ambient = case.thermal['ambient_c']
    hotspot = np.unravel_index(np.nanargmax(total), total.shape)
    contributions, sum_rise = {}, np.zeros_like(total)
    for source in case.dies:
        isolated = copy.deepcopy(raw)
        for die in isolated['chiplets']:
            if die['id'] != source.id:
                for block in die['blocks']:
                    block['power_w'] = 0
        _, temperature, _ = solve(isolated)
        rise = temperature - ambient
        sum_rise += rise
        contributions[source.id] = float(rise[hotspot])
    return dict(
        scope='assumed_linear_steady_model_diagnostics_only',
        physical_calibration=False, full_xyz_convergence_established=False,
        source_layer_refined=False, junction_temperature_validated=False,
        passive_refinement=rows,
        fixed_geometry_contributions=dict(
            hotspot_index_yx=list(map(int, hotspot)),
            hotspot_xy_mm=[float(case.mesh.x_centers_mm[hotspot[1]]),
                           float(case.mesh.y_centers_mm[hotspot[0]])],
            total_rise_k=float(total[hotspot] - ambient),
            rise_by_source_k=contributions,
            superposition_error_k=float(np.nanmax(abs(total - ambient - sum_rise))),
            interpretation='All material remains; contributions use the total-field hotspot, not separate maxima.'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, default=Path('examples/low_speed_gpio.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    case = load_case(args.case)
    if case.thermal['model'] != 'layered_package_steady':
        parser.error('a layered package case is required')
    if args.output.exists():
        parser.error('choose a fresh output file')
    report = diagnose(case.input_data)
    report['source_revision'] = source_revision()
    report['input_sha256'] = hashlib.sha256(args.case.read_bytes()).hexdigest()
    report['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print('Diagnostic complete; physical calibration and full XYZ convergence remain unvalidated.')


if __name__ == '__main__':
    main()
