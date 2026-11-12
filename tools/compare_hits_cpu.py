"""Local CPU same-equation smoke comparison; not a GPU speed benchmark."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import numpy as np
from scipy.sparse.linalg import spsolve

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.package import assemble_package
from chiplet_floorplanning.characterization import digest


def completion_status(cases, expected_profiles):
    actual = [case['profile'] for case in cases]
    finished = len(actual) == len(set(actual)) and set(actual) == set(expected_profiles)
    accepted = finished and all(case['receipt'].get('accepted') is True for case in cases)
    return dict(execution_complete=finished, all_solvers_accepted=accepted, complete=accepted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hits', type=Path, required=True)
    parser.add_argument('--witness', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.hits.resolve()))
    from core.thermal.operator import HiTS, ThermalOperator, EquationConvention, NodeRegion
    revision = subprocess.check_output(['git', '-C', str(args.hits), 'rev-parse', 'HEAD'], text=True).strip()
    report = dict(complete=False, execution_complete=False, all_solvers_accepted=False, hits_revision=revision, cpu_only=True,
                  source_sha256=digest(__file__), physical_calibration=False,
                  scope='three single-run API smoke checks, not statistical performance evidence or GPU qualification', cases=[])
    for profile in ('nominal', 'tx_power_125pct', 'cooling_800'):
        root = args.witness/(profile+'_slot1_rot180_witness')
        case = parse_case(json.loads((root/'placed.json').read_text()))
        power, _ = rasterize(case)
        a, b, sink, nodes, _, _ = assemble_package(case, power)
        regions = []
        for layer in sorted({node[0] for node in nodes}):
            locations = [i for i, node in enumerate(nodes) if node[0] == layer]
            regions.append(NodeRegion(locations[0], locations[-1]+1, 'SOLID',
                                     case.thermal['layers'][layer]['id'], layer, True))
        query = ThermalOperator(a, b, None,
            EquationConvention('K rise above ambient', 's', 'W/K', 'W', 'J/K', 'none',
                               'A theta = power', 'ambient removed by temperature-rise formulation'),
            'active layer-y-x', tuple(regions), 'chiplet_floorplanning',
            'saved witness package assembly', profile,
            ('geometry/materials/cooling', 'absent steady capacity', 'fixed spatial power'))
        start = perf_counter()
        reference = spsolve(a, b)
        direct_seconds = perf_counter()-start
        print(profile, 'nodes', len(b), 'direct seconds', direct_seconds, flush=True)
        start = perf_counter()
        with HiTS() as solver:
            result, receipt = solver.solve_steady(query)
        api_seconds = perf_counter()-start
        entry = dict(profile=profile, placed_sha256=digest(root/'placed.json'), nodes=len(b),
                     direct_solve_seconds=direct_seconds, hits_solve_api_seconds=api_seconds, receipt=receipt)
        if receipt['accepted']:
            entry.update(max_difference_k=float(np.max(abs(result-reference))),
                         energy_error_w=float(sink@result-b.sum()),
                         max_residual_w=float(np.max(abs(a@result-b))))
        report['cases'].append(entry)
        args.output.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(entry), flush=True)
    report.update(completion_status(report['cases'], ('nominal', 'tx_power_125pct', 'cooling_800')))
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    if not report['all_solvers_accepted']:
        raise RuntimeError('HiTS smoke execution ended with rejected or missing solves')


if __name__ == '__main__':
    main()
