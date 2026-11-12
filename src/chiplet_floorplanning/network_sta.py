"""Same-process 1.8 V TT SKY130 core-boundary multi-lane OpenSTA backend.

No pad, ESD, voltage translation, package signoff or characterized hot PHY is
implied. Linear interpolation of public 25/100 C NLDM tables is unvalidated.
"""

import json
from pathlib import Path
import re
import subprocess

from .characterization import sky_instance_model, digest
from .liberty_checks import groups, unique_group, read_table, lookup
from .network_reports import extract, NUMBER
from .shared_parasitics import SPEF_HEADER, tree_rc, spef_tree


def instances(case, contract):
    """Explicit local points, tied to the same transformed physical signal pins."""
    tx = contract['tx']; receivers = contract['receivers']; lanes = contract['lanes_per_receiver']
    if len(receivers) != 2 or type(lanes) is not int or not 4 <= lanes <= 8:
        raise ValueError('this backend requires one TX, two RX and 4..8 lanes per RX')
    if len({tx, *receivers}) != 3 or {d.id for d in case.dies} != {tx, *receivers}:
        raise ValueError('exactly the declared three chiplets required')
    dies = {d.id: d for d in case.dies}
    expected = {f'data_{r}_{l}' for r in range(2) for l in range(lanes)}
    if {n['id'] for n in case.links if n['kind']=='data'} != expected:
        raise ValueError('data lane identities must cover both receivers')
    clocks = [n for n in case.links if n['kind']=='clock']
    if [n['target']['chiplet'] for n in clocks] != receivers:
        raise ValueError('shared clock sink order must match receiver order')
    rows = {}
    def add(name, cell, die_id, port=None):
        die = dies[die_id]
        point = list(die.ports[port]) if port else [die.width/2, die.height/2]
        rows[name] = dict(cell=cell, chiplet=die_id, local_point_mm=point)
    add('clock_root', 'buf_8', tx)
    add('clock_trunk', 'buf_8', tx, clocks[0]['source']['port'])
    for r, receiver in enumerate(receivers):
        if clocks[r]['source']['chiplet'] != tx:
            raise ValueError('forwarded clock must originate at TX')
        add(f'bank_{r}', 'buf_8', tx)
        add(f'branch_{r}_cell', 'buf_8', receiver, clocks[r]['target']['port'])
        add(f'inv_{r}', 'inv_1', receiver, clocks[r]['target']['port'])
        for l in range(lanes):
            suffix = f'{r}_{l}'
            link = next(n for n in case.links if n['id']=='data_'+suffix)
            if link['source']['chiplet'] != tx or link['target']['chiplet'] != receiver:
                raise ValueError('data endpoint differs from timing netlist contract')
            add('tx_'+suffix, 'dfxtp_1', tx, link['source']['port'])
            add('data_cell_'+suffix, 'buf_8', tx, link['source']['port'])
            add('rx_'+suffix, 'dfxtp_1', receiver, link['target']['port'])
    return rows


def netlist(lanes):
    lines = [f'module fabric(input clk, input [{2*lanes-1}:0] d, output [{2*lanes-1}:0] q);',
             'wire common, forwarded;',
             'thermal_clock_root clock_root (.A(clk), .X(common));',
             'thermal_clock_trunk clock_trunk (.A(common), .X(forwarded));']
    for r in range(2):
        lines += [f'wire launch_{r}, branch_{r}, capture_{r};',
                  f'thermal_bank_{r} bank_{r} (.A(common), .X(launch_{r}));',
                  f'thermal_branch_{r}_cell branch_{r}_cell (.A(forwarded), .X(branch_{r}));',
                  f'thermal_inv_{r} inv_{r} (.A(branch_{r}), .Y(capture_{r}));']
        for l in range(lanes):
            s = f'{r}_{l}'; port = r*lanes+l
            lines += [f'wire txq_{s}, data_{s};',
                      f'thermal_tx_{s} tx_{s} (.CLK(launch_{r}), .D(d[{port}]), .Q(txq_{s}));',
                      f'thermal_data_cell_{s} data_cell_{s} (.A(txq_{s}), .X(data_{s}));',
                      f'thermal_rx_{s} rx_{s} (.CLK(capture_{r}), .D(data_{s}), .Q(q[{port}]));']
    return '\n'.join(lines+['endmodule', ''])


def script(models, contract, records):
    period = contract['period_ns']; fall = contract['fall_ns']; lanes = contract['lanes_per_receiver']
    if not 0 < fall < period or period < 20:
        raise ValueError('this core-boundary study is restricted to periods >=20 ns; not a PHY speed rating')
    lines = [f'read_liberty {name}.lib' for name in models]
    lines += ['read_verilog fabric.v', 'link_design fabric', 'set_delay_calculator simple_rc',
              f'create_clock -name launch -period {period} -waveform {{0 {fall}}} [get_ports clk]']
    for r in range(2):
        lines += [f'create_generated_clock -name capture_{r} -source [get_ports clk] -divide_by 1 -invert [get_pins inv_{r}/Y]']
    lines += ['set_propagated_clock [all_clocks]', 'set_clock_transition 0.1 [all_clocks]',
              'set_input_delay -clock launch 0.0 [get_ports d*]',
              'set_output_delay -clock launch 0.0 [get_ports q*]',
              'set_input_transition 0.1 [get_ports d*]', 'set_input_transition 0.1 [get_ports clk]',
              'set_load 0.01 [get_ports q*]',
              'set sta_crpr_enabled 0', 'read_spef package.spef',
              'puts "NETWORK_CHECKS_BEGIN"', 'check_setup -verbose',
              'report_check_types -max_slew -max_capacitance -min_pulse_width -violators',
              'puts "NETWORK_CHECKS_END"', 'report_clock_properties [all_clocks]']
    for name, record in records.items():
        lines += [f'puts "RC_BEGIN {name}"',
                  f'report_net -connections -verbose -digits 9 {record["design_net"]}', f'puts "RC_END {name}"']
    for r in range(2):
        for l in range(lanes):
            for check, delay in (('setup', 'max'), ('hold', 'min')):
                for edge in ('rise', 'fall'):
                    key = f'{r}_{l}_{check}_{edge}'
                    lines += [f'puts "NETWORK_BEGIN {key}"',
                        f'report_checks -from [get_cells tx_{r}_{l}] -{edge}_to [get_pins rx_{r}_{l}/D] -path_delay {delay} -format full_clock_expanded -fields {{slew cap input_pin}} -digits 9',
                        f'puts "NETWORK_END {key}"']
    return '\n'.join(lines)+'\n'


def audit_tables(paths, models):
    """Bounded NLDM lookup and independent setup/hold event arithmetic.

The same source tables are a numerical reference, not a SPICE validation.
Every reported launch/capture/data cell arc and RX constraint is covered.
"""
    parsed = {}
    for name, model in models.items():
        body = unique_group(Path(model['path']).read_text(), 'cell', model['cell'])
        parsed[name] = {pin: list(groups(content, 'timing')) for pin, content in groups(body, 'pin')}
    errors = []; count = 0
    for key, path in paths.items():
        r, l, check, edge = key.split('_'); s = f'{r}_{l}'; p = path['pins']
        # Output and preceding source slews are independent of geometrical length.
        arcs = [('clock_root', 'X', 'rise', .1, 'root_launch'),
                ('clock_root', 'X', 'fall', .1, 'root_capture'),
                ('bank_'+r, 'X', 'rise', p['root_launch']['slew_ns'], 'bank'),
                ('clock_trunk', 'X', 'fall', p['root_capture']['slew_ns'], 'trunk'),
                ('branch_'+r+'_cell', 'X', 'fall', p['branch_input']['slew_ns'], 'branch'),
                ('inv_'+r, 'Y', 'rise', p['branch']['slew_ns'], 'inverter'),
                ('tx_'+s, 'Q', edge, p['launch_ck']['slew_ns'], 'cq'),
                ('data_cell_'+s, 'X', edge, p['cq']['slew_ns'], 'data')]
        for name, pin, transition, slew, observed in arcs:
            timing = parsed[name][pin]
            if len(timing) != 1:
                raise ValueError('ambiguous core cell propagation arc')
            arc = timing[0][1]; point = [slew, p[observed]['cap_pf']]
            for kind, actual in [('cell_'+transition, p[observed]['delay_ns']),
                                 (transition+'_transition', p[observed]['slew_ns'])]:
                expected = lookup(read_table(arc, kind), point)
                errors.append(abs(expected-actual)); count += 1
        constraints = [arc for _, arc in parsed['rx_'+s]['D']
                       if re.search(r'timing_type\s*:\s*"?'+check+'_rising', arc)]
        if len(constraints) != 1:
            raise ValueError('ambiguous receiver timing constraint')
        value = lookup(read_table(constraints[0], edge+'_constraint'),
                       [p['capture_ck']['slew_ns'], p['receive_d']['slew_ns']])
        required = path['capture_arrival_ns']+(-value if check=='setup' else value)
        expected = required-path['data_arrival_ns'] if check=='setup' else path['data_arrival_ns']-required
        errors += [abs(required-path['required_ns']), abs(expected-path['slack_ns'])]
        count += 1
    worst = max(errors)
    if worst > 1e-5:
        raise ValueError(f'bounded core table/path reference mismatch {worst} ns')
    return dict(lookup_count=count, max_error_ns=worst, all_queries_in_table_domain=True,
                reference='independent_source_NLDM_lookup_not_SPICE_or_measurement')


def run_network(sta, model_root, folder, contract, locations, temperatures, fabric, nets, routes,
                electrical, edge_temperatures):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=False)
    models = {name: sky_instance_model(model_root, info['cell'], name, temperatures[name], folder/(name+'.lib'))
              for name, info in locations.items()}
    # Capacitance belongs to Liberty; the exported SPEF owns wire/via C only.
    pin_caps = {}; edge_caps = {}
    for name, model in models.items():
        cell = unique_group(Path(model['path']).read_text(), 'cell', model['cell'])
        pin = 'D' if locations[name]['cell']=='dfxtp_1' else 'A'
        pin_body = unique_group(cell, 'pin', pin)
        match = re.search(r'\bcapacitance\s*:\s*('+NUMBER+')', pin_body)
        if not match:
            raise ValueError('missing receiver input capacitance')
        pin_caps[name] = float(match[1])
        edge_caps[name] = {}
        for transition in ('rise', 'fall'):
            found = re.search(r'\b'+transition+'_capacitance'+r'\s*:\s*('+NUMBER+')', pin_body)
            edge_caps[name][transition] = float(found[1]) if found else pin_caps[name]
    text = SPEF_HEADER; records = {}
    for net in nets:
        if net.kind=='clock':
            design_net = 'forwarded'; source = 'clock_trunk:X'
            targets = [f'branch_{r}_cell' for r in range(2)]; pins = [n+':A' for n in targets]
        else:
            suffix = net.name.removeprefix('data_'); design_net = net.name; source = 'data_cell_'+suffix+':X'
            targets = ['rx_'+suffix]; pins = [targets[0]+':D']
        factors = {e: 1+electrical['alpha_per_k']*(t-electrical['reference_temperature_c'])
                   for e, t in edge_temperatures[net.name].items()}
        rc = tree_rc(fabric, net, routes[net.name], r_ohm_per_mm=electrical['r_ohm_per_mm'],
                     c_pf_per_mm=electrical['c_pf_per_mm'], via_r_ohm=electrical['via_r_ohm'],
                     via_c_pf=electrical['via_c_pf'], sink_cap_pf=[pin_caps[n] for n in targets],
                     resistance_factors=factors)
        text += spef_tree(design_net, source, pins, rc)
        records[net.name] = dict(design_net=design_net, source_pin=source, sink_pins=pins,
            sink_capacitance_by_edge_pf={edge: sum(edge_caps[n][edge] for n in targets) for edge in ('rise', 'fall')}, **rc)
    files = {'package.spef': text, 'fabric.v': netlist(contract['lanes_per_receiver']),
             'run.tcl': script(models, contract, records)}
    for name, content in files.items():
        (folder/name).write_text(content, encoding='utf-8')
    execution = subprocess.run([str(Path(sta).resolve(strict=True)), '-no_init', '-exit', 'run.tcl'],
                               cwd=folder, capture_output=True, text=True, timeout=120)
    log = execution.stdout+execution.stderr; (folder/'sta.log').write_text(log, encoding='utf-8')
    result = dict(status='unresolved', physical_interface_qualified=False, models=models, rc=records,
                  executable_sha256=digest(sta),
                  input_sha256={p.name: digest(p) for p in sorted(folder.iterdir()) if p.suffix in ('.lib', '.spef', '.v', '.tcl')},
                  log_sha256=digest(folder/'sta.log'), returncode=execution.returncode)
    if execution.returncode:
        result['reason'] = 'OpenSTA execution failed'; return result
    try:
        paths = extract(log, 2, contract['lanes_per_receiver'], True, core_pins=True)
        # Whole conductor ownership and one shared clock annotation.
        cap_errors = []
        for name, rc in records.items():
            matches = re.findall(rf'RC_BEGIN {name}\n(.*?)RC_END {name}', log, re.S)
            if len(matches) != 1:
                raise ValueError('missing unique net annotation')
            for label in ('Wire capacitance', 'Pin capacitance', 'Total capacitance'):
                lines = re.findall(label+r':([^\n]+)', matches[0])
                if len(lines) != 1:
                    raise ValueError('missing capacitance annotation')
                values = re.findall(NUMBER, lines[0])
                if len(values) not in (1, 2):
                    raise ValueError('invalid rise/fall capacitance annotation')
                for transition, value in zip(('rise', 'fall'), values if len(values)==2 else values*2):
                    expected = (rc['total_parasitic_pf'] if label != 'Pin capacitance' else 0.)
                    if label != 'Wire capacitance':
                        expected += rc['sink_capacitance_by_edge_pf'][transition]
                    cap_errors.append(abs(float(value)-expected))
            if not re.search(r'Number of drivers:\s+1\b', matches[0]) or not re.search(
                    rf'Number of loads:\s+{len(rc["sink_indices"])}\b', matches[0]):
                raise ValueError('driver or shared-clock sink ownership mismatch')
        if max(cap_errors) > 1e-6:
            raise ValueError('SPEF/Liberty capacitance ownership mismatch')
        result['table_audit'] = audit_tables(paths, models)
        setup = min((v['slack_ns'], k) for k, v in paths.items() if '_setup_' in k)
        hold = min((v['slack_ns'], k) for k, v in paths.items() if '_hold_' in k)
        result.update(status='analyzed', paths=paths, worst_setup_ns=setup[0], worst_hold_ns=hold[0],
                      critical_setup=setup[1], critical_hold=hold[1], timing_feasible=min(setup[0], hold[0])>=0,
                      max_annotation_capacitance_error_pf=max(cap_errors))
    except ValueError as error:
        result['reason'] = str(error)
        if 'electrical violation' in str(error) and 'VIOLATED' in log:
            result['status'] = 'electrical_rejected'
    return result
