"""Check necessary heat-network physics and expose the declared channel approximation."""

import argparse
import copy
import json
from pathlib import Path

import numpy as np
from scipy.sparse.linalg import spsolve

from chiplet_floorplanning.interconnect import estimate_links
from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.package import assemble_package
from chiplet_floorplanning.power import rasterize
from validation.pad_sources import digest
from validation.physical_invariants import heat_ledger
from validation.sources import git_revision, write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    base = json.loads(Path('examples/low_speed_gpio.json').read_text())
    variants = {}
    for name in ('nominal', 'bottom_cooled', 'two_sided', 'anisotropic'):
        config = copy.deepcopy(base)
        if name == 'bottom_cooled':
            config['thermal'].update(top_h_w_m2k=0.0, bottom_h_w_m2k=1000.0)
        elif name == 'two_sided':
            config['thermal'].update(top_h_w_m2k=1000.0, bottom_h_w_m2k=1000.0)
        elif name == 'anisotropic':
            layer = config['thermal']['layers'][0]
            k = layer.pop('conductivity_w_mk')
            layer['conductivity_xyz_w_mk'] = [k, k / 2, k / 4]
        variants[name] = config
    records = []
    for name, config in variants.items():
        case = parse_case(config)
        power, _ = rasterize(case)
        matrix, rhs, sink, nodes, _, _ = assemble_package(case, power)
        rise = spsolve(matrix, rhs)
        ambient_k = case.thermal['ambient_c'] + 273.15
        ledger = heat_ledger(matrix, sink, rise + ambient_k, ambient_k, rhs)
        records.append(dict(name=name, node_count=len(nodes), peak_c=float(rise.max() + case.thermal['ambient_c']),
                            config=config, ledger=ledger, necessary_invariants_passed=True))
    case = parse_case(base)
    channel = []
    cfg = base['interconnect']
    for link in estimate_links(case):
        # Same ideal uniform, nonmagnetic, parallel-plate geometry as the existing C model.
        # This is an omitted-term scale estimate, not extracted inductance or an RC acceptance rule.
        length_m = link['modeled_length_mm'] * 1e-3
        inductance_h = 4 * np.pi * 1e-7 * cfg['dielectric_height_um'] / cfg['width_um'] * length_m
        capacitance_f = link['assumed_c_pf'] * 1e-12
        channel.append(dict(link_id=link['id'], length_mm=link['modeled_length_mm'], resistance_ohm=link['assumed_r_ohm'],
                            capacitance_pf=link['assumed_c_pf'], ideal_external_inductance_nh=inductance_h * 1e9,
                            ideal_tem_flight_ps=float(np.sqrt(inductance_h * capacitance_f) * 1e12),
                            inductive_to_resistive_impedance_ratio=[dict(frequency_ghz=f, ratio=2*np.pi*f*1e9*inductance_h/link['assumed_r_ohm']) for f in (0.1, 1.0, 10.0)],
                            rc_approximation_qualified=False, scope='ideal-geometry scale estimate; omits return-path details, fringing, bumps, internal inductance, skin/proximity effects and dielectric loss'))
    result = dict(source=git_revision(Path.cwd()), source_example_sha256=digest(Path('examples/low_speed_gpio.json').read_bytes()),
                  implementation_sha256={name: digest(Path(name).read_bytes()) for name in (
                      'tools/audit_physical_invariants.py', 'tools/validation/physical_invariants.py',
                      'src/chiplet_floorplanning/package.py', 'src/chiplet_floorplanning/interconnect.py',
                      'src/chiplet_floorplanning/power.py', 'src/chiplet_floorplanning/model.py',
                      'src/chiplet_floorplanning/mesh.py')},
                  thermal_cases=records, channel_scale_checks=channel, physical_model_qualified=False,
                  necessary_thermal_invariants_passed=all(r['necessary_invariants_passed'] for r in records),
                  scope='necessary conservation/passivity/positive-temperature checks of declared models; material, boundary, power and channel fidelity remain uncalibrated')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(json.dumps(dict(thermal_cases=len(records), all_necessary_invariants_passed=result['necessary_thermal_invariants_passed'],
                          maximum_balance_error_w=max(abs(r['ledger']['energy_balance_error_w']) for r in records),
                          channel_scale_checks=channel), indent=2))


if __name__ == '__main__':
    main()
