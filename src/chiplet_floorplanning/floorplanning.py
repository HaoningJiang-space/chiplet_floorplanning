"""One placement contract from geometry through thermal fields and real STA.

This first backend is a mechanism study with real core-cell NLDM tables and
assumed packaging. It is not a qualified electrical Pad or measured package.
"""

import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np

from .characterization import digest, sample_instance_temperature
from .layout import relocate_design
from .model import parse_case
from .network_sta import instances, run_network
from .pin_fabric import pin_fabric
from .power import rasterize
from .routing_graph import route_greedy, audit, cut_certificate, verify_cut
from .thermal import solve_steady


def serial(value):
    if isinstance(value, dict):
        return {str(k): serial(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return [serial(v) for v in sorted(value)]
    if isinstance(value, (tuple, list)):
        return [serial(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def write_json(path, value):
    Path(path).write_text(json.dumps(serial(value), indent=2, allow_nan=False)+'\n', encoding='utf-8')


def layer_grid(case, thermal, temperature, name):
    if case.thermal['model'] != 'layered_package_steady':
        raise ValueError('integrated wire coupling requires an explicit package layer')
    z = [layer['id'] for layer in case.thermal['layers']].index(name)
    grid = np.full((case.ny, case.nx), np.nan)
    for (layer, y, x), value in zip(thermal['node_indices_layer_y_x'], thermal['all_node_temperature_c']):
        if layer == z:
            grid[y, x] = value
    if not np.isfinite(grid).all():
        raise ValueError('routing temperature layer must cover the entire package')
    return grid


def sample_plane(case, grid, point):
    """Centre-linear interpolation, with explicit boundary clamping."""
    x, y = point[:2]
    values = [np.interp(x, case.mesh.x_centers_mm, row) for row in grid]
    return float(np.interp(y, case.mesh.y_centers_mm, values))


def evaluate(layout, configuration):
    """Evaluate one placement and one declared routing policy, with paired STA.

    configuration contains fixed scientific inputs plus a runtime object with
    output, sta and model_root paths. There is no hidden optimizer penalty.
    Invalid inputs and search failures never become global infeasibility claims.
    """
    cfg = copy.deepcopy(configuration); runtime = cfg.pop('runtime')
    output = Path(runtime['output']); output.mkdir(parents=True, exist_ok=False)
    inputs = dict(layout=layout, configuration=cfg)
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True, allow_nan=False).encode()).hexdigest()
    write_json(output/'inputs.json', inputs)
    result = dict(input_sha256=fingerprint, status='invalid_candidate', geometry_feasible=False,
                  routing_status='not_run', timing_status='not_run', physical_interface_qualified=False,
                  complete_package_signoff=False, model_scope='SKY130_TT_1v8_core_boundary_with_assumed_package',
                  numerical_validation='pending', physical_optimum_certified=False)
    def finish():
        write_json(output/'report.json', result)
        return result
    try:
        case = relocate_design(parse_case(cfg['design']), layout, grid=cfg.get('grid'))
        fabric, nets, pins = pin_fabric(case, cfg['routing'])
        locations = instances(case, cfg['interface'])
    except (ValueError, KeyError, TypeError) as error:
        result['reason'] = str(error)
        return finish()
    result.update(geometry_feasible=True, physical_pins=pins)
    write_json(output/'placed.json', case.input_data)
    routed = route_greedy(fabric, nets, cfg['routing'].get('order'))
    result['routing_status'] = routed['status']
    write_json(output/'routing.json', dict(fabric=asdict(fabric), nets=[asdict(n) for n in nets], result=routed))
    # Heat is evaluated even for an unresolved route: it supplies a valid lower
    # bound only under this declared fixed-power, no wire self-heating model.
    power, blocks = rasterize(case)
    temperature, thermal = solve_steady(case, power)
    plane = layer_grid(case, thermal, temperature, cfg['electrical']['thermal_layer'])
    np.savez_compressed(output/'temperature.npz', die_c=temperature, routing_layer_c=plane,
                        x_mm=case.mesh.x_centers_mm, y_mm=case.mesh.y_centers_mm)
    result['thermal'] = {k: v for k, v in thermal.items() if k not in ('all_node_temperature_c', 'node_indices_layer_y_x')}
    result['temperature_sha256'] = digest(output/'temperature.npz')
    result['power_blocks'] = blocks
    result['power_assumption'] = 'fixed_workload_includes_IO_block_power_no_incremental_wire_loss_or_leakage_feedback'
    if routed['status'] != 'feasible':
        result.update(status='routing_unresolved', reason='greedy failure is not an infeasibility proof')
        for split in range(fabric.nx-1):
            certificate = cut_certificate(fabric, nets, split)
            if certificate['proven_infeasible'] and verify_cut(fabric, nets, certificate):
                result.update(status='routing_infeasible', routing_status='certified_infeasible',
                              reason='complete resource cut demand exceeds capacity', routing_certificate=certificate)
                break
        return finish()
    result['routing_audit'] = audit(fabric, nets, routed['routes'])
    if not result['routing_audit']['fabric_legal']:
        raise ValueError('accepted router output failed independent resource audit')
    local = {}; local_evidence = {}
    for name, location in locations.items():
        local[name], local_evidence[name] = sample_instance_temperature(
            case, temperature, location['chiplet'], location['local_point_mm'])
    result['local_temperature_c'] = local
    result['temperature_mapping'] = local_evidence
    result['wire_temperature_mapping'] = 'endpoint_mean_of_bilinear_interposer_layer_centres_boundary_clamped_same_field_for_both_signal_layers'
    edge_temperatures = {}
    for net in nets:
        edge_temperatures[net.name] = {e: sum(sample_plane(case, plane, fabric.coordinates_mm(n)) for n in e)/2
                                     for e in routed['routes'][net.name]}
    write_json(output/'wire-temperatures.json', edge_temperatures)
    result['timing'] = {}
    for mode, feedback in (('reference', False), ('feedback', True)):
        temperatures = local if feedback else {n: cfg['interface']['reference_temperature_c'] for n in local}
        wires = edge_temperatures if feedback else {
            name: {e: cfg['interface']['reference_temperature_c'] for e in values}
            for name, values in edge_temperatures.items()}
        if any(not 25 <= t <= 100 for t in temperatures.values()):
            result['timing'][mode] = dict(status='model_domain_rejected', reason='core temperature outside 25..100 C')
            continue
        timing = run_network(runtime['sta'], runtime['model_root'], output/mode, cfg['interface'],
                             locations, temperatures, fabric, nets, routed['routes'], cfg['electrical'], wires)
        write_json(output/mode/'report.json', timing)
        result['timing'][mode] = {k: v for k, v in timing.items() if k not in ('rc', 'models')}
        result['timing'][mode]['model_assignments'] = {
            n: {k: v for k, v in m.items() if k != 'path'} for n, m in timing['models'].items()}
        result['timing'][mode]['parasitics'] = {n: dict(
            unique_length_mm=sum(e['length_mm'] for e in rc['conductors']),
            total_package_parasitic_pf=rc['total_parasitic_pf'],
            total_package_sink_shunt_pf=rc['total_package_sink_shunt_pf'],
            total_sink_capacitance_pf=rc['total_sink_pin_pf'],
            sum_conductor_resistance_ohm=sum(e['resistance_ohm'] for e in rc['conductors']),
            nodal_relative_residual=rc['nodal_relative_residual']) for n, rc in timing['rc'].items()}
    if all(t['status']=='analyzed' for t in result['timing'].values()):
        result.update(status='analyzed', timing_status='analyzed', numerical_validation='resource_energy_RC_and_NLDM_path_checks_passed')
        a, b = (result['timing'][mode] for mode in ('reference', 'feedback'))
        result['feedback_slack_change_ns'] = {key: b['paths'][key]['slack_ns']-row['slack_ns'] for key, row in a['paths'].items()}
        result['feasible_reference'] = a['timing_feasible']
        result['feasible_feedback'] = b['timing_feasible']
    else:
        result.update(status='timing_unresolved', timing_status='not_fully_admitted')
    return finish()
