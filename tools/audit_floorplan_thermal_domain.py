"""Refine the entire small placement thermal domain, without rerunning STA."""

import argparse
import json
from pathlib import Path

from chiplet_floorplanning.characterization import digest
from chiplet_floorplanning.floorplanning import write_json
from chiplet_floorplanning.layout import relocate_design
from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.thermal import solve_steady


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    frozen = json.loads((args.benchmark/'frozen-inputs.json').read_text())
    for path, expected in frozen['source_sha256'].items():
        if digest(path)!=expected:
            raise ValueError('frozen evaluation source changed: '+path)
    result = dict(complete=False, source_sha256=digest(__file__),
                  benchmark_inputs_sha256=digest(args.benchmark/'frozen-inputs.json'), profiles={},
                  scope='numerical_xy_refinement_same_assumed_stack_not_independent_thermal_calibration')
    for condition in ('nominal', 'tx_power_125pct', 'cooling_800'):
        design = parse_case(frozen['profiles'][condition]['design'])
        result['profiles'][condition] = {}
        for factor in (2, 4):
            grid = {**design.input_data['grid'], 'nx': design.nx*factor, 'ny': design.ny*factor}
            rows = []
            for name, layout in frozen['layouts'].items():
                case = relocate_design(design, layout, grid=grid)
                power, _ = rasterize(case); _, summary = solve_steady(case, power)
                rows.append(dict(layout_id=name, peak_c=summary['peak_c'], actual_nx=case.nx, actual_ny=case.ny,
                                 energy_balance_error_w=summary['energy_balance_error_w']))
            result['profiles'][condition][factor] = sorted(rows, key=lambda r: (r['peak_c'], r['layout_id']))
            write_json(args.output, result)
            print(condition, factor, result['profiles'][condition][factor][:2], flush=True)
    result.update(complete=True, additional_thermal_solves=72,
                  package_load_25ff='same_thermal_problem_as_nominal_electrical_load_does_not_change_fixed_power')
    write_json(args.output, result)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
