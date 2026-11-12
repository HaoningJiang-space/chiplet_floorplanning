"""Enrich numerical thermal snapshots without consulting measured temperatures."""

import argparse
import ast
import gc
import json
from pathlib import Path

import numpy as np

from audit_ttc_package_transient import physical_flux_check, pulse
from validation.measured_sources import digest
from validation.measured_thermal import patterns
from validation.sources import write_json
from validation.ttc_package import build
from validation.ttc_reduction import SHIFTS, snapshot_bank, project, frequency_reference


ENRICHED_SHIFTS = (
    SHIFTS[-1],
    tuple([0.]+[10.**x for x in np.arange(-3., 7.01, .5)]),
    tuple([0.]+[10.**x for x in np.arange(-3., 7.01, .25)]),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior', type=Path, default=Path('results/physical-calibration/ttc-package-transient-v1'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--group', choices=('heatsink', 'heatsink_with_fan'), default='heatsink')
    parser.add_argument('--model', choices=('C', 'P'), default='C')
    args = parser.parse_args()
    prior = json.loads((args.prior/'frozen-inputs.json').read_text())
    # Exact model and numerical implementation must match the retained full-order
    # reference; do not silently reuse results after a physics/code change.
    for path, expected in prior['code_sha256'].items():
        if Path(path).name == 'audit_ttc_package_transient.py':
            # The driver can gain cache/CLI support; compare exactly the two
            # numerical functions imported by this diagnostic instead.
            def selected_functions(file):
                return [ast.dump(n) for n in ast.parse(file.read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name in ('pulse', 'physical_flux_check')]
            if selected_functions(Path(path)) != selected_functions(args.prior/Path(path).name):
                raise ValueError('reference pulse/flux implementation changed')
            continue
        if digest(Path(path)) != expected:
            raise ValueError('reference source changed: '+path)
    key = args.group+'_'+args.model+'_level0'
    source = args.prior/key
    prior_controls = json.loads((source/'numerical-controls.json').read_text())
    full = np.load(source/'numerical-controls.npz')
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(shifts_per_s=ENRICHED_SHIFTS, group=args.group, model=args.model, level=0,
                  source_frozen_sha256=digest(args.prior/'frozen-inputs.json'),
                  source_controls_sha256=digest(source/'numerical-controls.npz'),
                  code_sha256={str(Path(__file__)):digest(Path(__file__))},
                  measured_data_used_for_enrichment=False, physical_model_qualified=False, orders=[])
    write_json(args.output/'frozen.json', report)
    g, loss, b, h, assembly, geometry = build(prior['geometry'], prior['boundary'], args.group, 0, args.model)
    if geometry != json.loads((source/'geometry.json').read_text()):
        raise ValueError('full-order reference geometry changed')
    c = np.concatenate([block.capacity.ravel() for block in assembly.blocks])
    groups = [block.ids.ravel() for block in assembly.blocks]
    power = np.array(list(patterns().values())).T
    omegas = [.003, .03, .3, 3., 30., 300.]
    references = frequency_reference(g, c, b, h, omegas)
    bank, audits = snapshot_bank(g, c, b, ENRICHED_SHIFTS[-1], progress=lambda x:print('snapshot', x, flush=True))
    report['snapshots'] = audits
    for index, shifts in enumerate(ENRICHED_SHIFTS):
        reduced = project(g, c, b, h, loss, groups, bank, shifts)
        steps = reduced.steps(power, np.r_[0., np.geomspace(1e-6, 2000., 160)])
        pulse_values = pulse(reduced, power)
        entry = dict(index=index, audit=reduced.audit,
                     max_interface_flux_coefficient_error=physical_flux_check(reduced, assembly),
                     frequency_errors_k=[float(abs((reduced.frequency(w)-references[w]) @ power).max()) for w in omegas],
                     minimum_positive_step_k=float(steps.min()),
                     maximum_step_decrease_k=max(0., -float(np.diff(steps, axis=0).min())),
                     pulse_errors_k={k:float(abs(pulse_values[k]-full['richardson_'+k]).max()) for k in ('sensors', 'body_means')})
        entry['fixed_mesh_numerical_screen'] = bool(max(entry['frequency_errors_k']) < .01 and
            entry['minimum_positive_step_k'] > -1e-8 and entry['maximum_step_decrease_k'] < 1e-8 and
            max(entry['pulse_errors_k'].values()) < .02 and
            max(prior_controls['backward_euler'][k+'_extrapolation_change_k'] for k in ('sensors', 'body_means')) < .01)
        report['orders'].append(entry)
        write_json(args.output/'report.json', report)
        print('enrichment', entry, flush=True)
        del reduced
        gc.collect()
    report['complete'] = True
    write_json(args.output/'report.json', report)


if __name__ == '__main__':
    main()
