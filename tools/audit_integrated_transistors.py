"""Replay the complete nominal core fabric with explicit transistors and RC.

This is a cross-model diagnostic, not matched PEX characterization or Pad
qualification. It preserves eight lanes and both branches of the shared clock.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

import numpy as np

from chiplet_floorplanning.characterization import digest
from validation.decision_evidence import verify_saved_sta_files
from validation.pad_sources import prepare
from validation.pad_spice import crossing_ns


def build_fabric(verilog, receipt):
    connections = {}
    for model, instance, ports in re.findall(r'(thermal_\w+)\s+(\w+)\s*\(([^;]+)\);', verilog):
        connections[instance] = dict(re.findall(r'\.(\w+)\(([^)]+)\)', ports))
        if model != receipt['models'][instance]['cell']:
            raise ValueError('Verilog and receipt model differ')
    if set(connections) != set(receipt['models']) or len(connections) != 32:
        raise ValueError('expected complete 32-cell eight-lane fabric')
    wires, elements = {}, []
    for net, rc in receipt['rc'].items():
        name = lambda index: f'wire_{net}_{index}'
        wires[rc['source_pin']] = name(rc['source_index'])
        for pin, index in zip(rc['sink_pins'], rc['sink_indices']):
            if pin in wires:
                raise ValueError('duplicate route terminal')
            wires[pin] = name(index)
        # Only conductor/shunt C. Receiver capacitance is supplied by MOS devices.
        for i, cap in enumerate(rc['node_parasitic_pf']):
            if cap < 0:
                raise ValueError('negative parasitic capacitance')
            if cap:
                elements.append(f'C_{net}_{i} {name(i)} 0 {cap:.16g}p')
        for i, edge in enumerate(rc['conductors']):
            if edge['resistance_ohm'] <= 0:
                raise ValueError('nonpositive resistance')
            elements.append(f'R_{net}_{i} {name(edge["a"])} {name(edge["b"])} {edge["resistance_ohm"]:.16g}')
    nodes = {}
    for instance, ports in connections.items():
        node = lambda port: wires.get(instance+':'+port, ports[port].replace('[', '_').replace(']', ''))
        if set(ports) == {'A', 'X'}:
            pins, cell = [node('A'), '0', '0', 'vdd', 'vdd', node('X')], 'buf_8'
        elif set(ports) == {'A', 'Y'}:
            pins, cell = [node('A'), '0', '0', 'vdd', 'vdd', node('Y')], 'inv_1'
        elif set(ports) == {'CLK', 'D', 'Q'}:
            pins, cell = [node('CLK'), node('D'), '0', '0', 'vdd', 'vdd', node('Q')], 'dfxtp_1'
        else:
            raise ValueError('unsupported primitive mapping')
        if not any(f'sky_{cell}_tt_' in source for source in receipt['models'][instance]['source_files']):
            raise ValueError('source cell identity mismatch')
        elements.append(f'X_{instance} '+ ' '.join(pins)+f' sky130_fd_sc_hd__{cell}')
        nodes.update({instance+':'+port: node(port) for port in ports})
    return elements, nodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.reference, args.output
    receipt = json.loads((root/'report.json').read_text())
    verify_saved_sta_files(receipt, root)
    if any(m['temperature_c'] != 25 or m['voltage_v'] != 1.8 or m['process'] != 'tt' for m in receipt['models'].values()):
        raise ValueError('this experiment is restricted to uniform TT 25 C 1.8 V')
    tcl = (root/'run.tcl').read_text()
    required = ('-period 20.0 -waveform {0 10.0}', 'set_input_transition 0.1 [get_ports clk]',
                'set_load 0.01 [get_ports q*]')
    if not all(line in tcl for line in required):
        raise ValueError('different STA stimulus contract')
    out.mkdir(exist_ok=False)
    primitive = prepare(Path('local/pad-spice'))
    sources = {
        'buf_8': ('core-buf-repro-v1/buf_8.spice', '98bafb7bbd4aa107e9b0090ee241f30a6a84aa5b394bb8eaca5b189a207cd5c7'),
        'inv_1': ('core-inverter-v2/inv_1.spice', '1099e3641c46d241852db47974540b3ad161e20e01b74f2fd5cc152627011909'),
        'dfxtp_1': ('core-ff-cq-v1/dfxtp_1.spice', '39049c3c6a74ac24fdc0d93528dd5b0e15f7ef51729008913bdeeee0d8ead2df')}
    includes = []
    for cell, (path, sha) in sources.items():
        source = Path('results/physical-calibration')/path
        if digest(source) != sha:
            raise ValueError('pinned cell netlist mismatch')
        target = out/(cell+'.spice')
        target.write_bytes(source.read_bytes())
        includes.append(f'.include "{target.resolve().as_posix()}"')
    elements, nodes = build_fabric((root/'fabric.v').read_text(), receipt)
    observed = ['clk']+list(dict.fromkeys(nodes.values()))
    indices = {node: i+1 for i, node in enumerate(observed)}
    init = out/'empty-init'
    init.mkdir()
    (init/'spinit').write_text('* explicit primitives only\n')
    exe = Path('local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe').resolve()
    lib = Path('local/pad-spice/sky130A/libs.tech/ngspice/sky130.lib.spice').resolve()
    report = dict(complete=False, physical_qualified=False, source_sha256=digest(__file__),
        reference_receipt_sha256=digest(root/'report.json'), executable_sha256=digest(exe),
        primitive_sources=primitive, cell_sources=sources, observed_nodes=observed,
        scope='full eight-lane core transistor cross-model comparison; no Pad, setup/hold characterization or local temperature feedback', cases=[])
    ramp = .1/.6
    clock = '0 0 '
    for start in (1., 21., 41.):
        clock += f'{start}n 0 {start+ramp}n 1.8 {start+10}n 1.8 {start+10+ramp}n 0 '
    clock += '60n 0'
    for step in (5., 2.5):
        folder = out/f'step_{step:g}ps'
        folder.mkdir()
        lines = ['Complete transistor fabric diagnostic', f'.lib "{lib.as_posix()}" tt', *includes,
            '.options scale=1u reltol=1e-6 abstol=1e-13 vntol=1e-8', '.temp 25',
            'VDD vdd 0 1.8', f'VCLK clk 0 PWL({clock})', *elements]
        for i in range(8):
            lines += [f'VD{i} d_{i} 0 PWL(0 0 15n 0 {15+ramp}n 1.8 35n 1.8 {35+ramp}n 0 60n 0)',
                      f'CQ{i} q_{i} 0 .01p']
        lines += ['.control', 'set numdgt=15', 'set wr_singlescale', f'tran {step}p 60n 0 {step}p',
                  'wrdata wave.txt '+' '.join(f'v({n})' for n in observed)+' i(VDD) i(VCLK)', 'quit', '.endc', '.end']
        (folder/'deck.sp').write_text('\n'.join(lines)+'\n')
        run = subprocess.run([str(exe), '-n', '-D', 'ngbehavior=hsa', '-b', 'deck.sp'], cwd=folder,
            capture_output=True, text=True, timeout=1800,
            env={**os.environ, 'SPICE_SCRIPTS': str(init.resolve())})
        log = run.stdout+run.stderr
        (folder/'ngspice.log').write_text(log)
        known = 'Warning: m=xx on .subckt line will override multiplier m hierarchy!'
        if run.returncode or re.search(r'(?im)^\s*(?:error|fatal|warning):', log.replace(known, '')):
            raise ValueError('unadmitted simulator failure')
        wave = np.loadtxt(folder/'wave.txt')
        t = wave[:, 0]*1e9
        if not np.isfinite(wave).all() or np.any(np.diff(t) <= 0) or t[-1] < 59.999:
            raise ValueError('invalid waveform')
        records = []
        for group in range(2):
            for lane in range(4):
                suffix = f'{group}_{lane}'
                for edge, launch in (('rise', 21.), ('fall', 41.)):
                    path = receipt['paths'][suffix+'_setup_'+edge]
                    def cross(node, start, rising):
                        mask = (t >= start-.05) & (t <= start+5.)
                        return crossing_ns(t[mask], wave[mask, indices[node]], .9, rising)
                    origin = cross('clk', launch, True)
                    data_time = cross(nodes['rx_'+suffix+':D'], launch, edge == 'rise')-origin
                    capture_time = cross(nodes[f'inv_{group}:Y'], launch+10, True)-origin
                    window = (t >= launch+14) & (t <= launch+15)
                    q = wave[window, indices[nodes['rx_'+suffix+':Q']]]
                    if not len(q) or np.max(abs(q-(1.8 if edge == 'rise' else 0.))) > .018:
                        raise ValueError('receiver capture failed')
                    # This is available setup time BEFORE a receiver setup requirement.
                    available = capture_time-data_time
                    sta_available = path['capture_arrival_ns']-path['data_arrival_ns']
                    records.append(dict(lane=suffix, edge=edge, data_arrival_ns=data_time,
                        capture_arrival_ns=capture_time, available_setup_window_ns=available,
                        sta_available_setup_window_ns=sta_available,
                        window_difference_ps=(available-sta_available)*1000,
                        data_difference_ps=(data_time-path['data_arrival_ns'])*1000,
                        capture_difference_ps=(capture_time-path['capture_arrival_ns'])*1000,
                        logical_capture_passed=True))
        report['cases'].append(dict(step_ps=step, paths=records,
            artifacts_sha256={name: digest(folder/name) for name in ('deck.sp', 'wave.txt', 'ngspice.log')}))
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
        print('completed', step, 'ps', len(records), 'paths', flush=True)
    report['complete'] = True
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
