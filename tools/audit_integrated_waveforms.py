"""Exploratory independent SPICE replay; ideal ramp, not a qualified driver."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
import numpy as np
from scipy.integrate import cumulative_trapezoid
from audit_integrated_channels import moments
from chiplet_floorplanning.liberty_checks import unique_group
from chiplet_floorplanning.characterization import digest
from validation.decision_evidence import verify_saved_sta_files
from validation.pad_spice import crossing_ns

parser = argparse.ArgumentParser()
parser.add_argument('input', type=Path)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root, out = args.input, args.output
out.mkdir(exist_ok=False)
init = out/'empty-init'; init.mkdir(); (init/'spinit').write_text('* passive R/C only\n')
exe = Path('local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe').resolve()
answer = dict(complete=False, source_sha256=digest(__file__), executable_sha256=digest(exe),
              scope='ideal prescribed linear driver waveform and constant Liberty pin C; no Pad or physical qualification', cases=[])
for mode in ('reference', 'feedback'):
    receipt = json.loads((root/mode/'report.json').read_text())
    verify_saved_sta_files(receipt, root/mode)
    specs = [(n,e,'data') for n in receipt['rc'] if n.startswith('data_') for e in ('rise','fall')]
    specs.append(('forwarded_clock','fall','trunk'))
    for net, edge, incoming in specs:
        rc = receipt['rc'][net]
        key = '0_0_setup_rise' if net=='forwarded_clock' else net.removeprefix('data_')+'_setup_'+edge
        path = receipt['paths'][key]
        slew = path['pins'][incoming]['slew_ns']
        cap = np.array(rc['node_parasitic_pf'])
        for index, pin in zip(rc['sink_indices'], rc['sink_pins']):
            instance, port = pin.split(':'); model = receipt['models'][instance]
            body = unique_group(unique_group(Path(model['path']).read_text(), 'cell', model['cell']), 'pin', port)
            match = re.search(r'\b'+edge+r'_capacitance\s*:\s*([-+0-9.eE]+)', body)
            if match is None:
                match = re.search(r'\bcapacitance\s*:\s*([-+0-9.eE]+)', body)
            cap[index] += float(match[1])
        for step in (1., .5):
            name = f'{mode}_{net}_{edge}_{step:g}ps'; folder = out/name; folder.mkdir()
            source = rc['source_index']; ramp = slew/.6
            low, high = (0., 1.8) if edge=='rise' else (1.8, 0.)
            lines = ['Independent prescribed-ramp RC replay', '.options reltol=1e-7 abstol=1e-15 vntol=1e-9',
                     f'Vstim n{source} 0 PWL(0 {low} 0.2n {low} {0.2+ramp:.15g}n {high})']
            lines += [f'C{i} n{i} 0 {c:.15g}p' for i,c in enumerate(cap) if c>0]
            lines += [f'R{i} n{e["a"]} n{e["b"]} {e["resistance_ohm"]:.15g}' for i,e in enumerate(rc['conductors'])]
            lines += ['.control', 'set wr_singlescale', 'set numdgt=15',
                      f'tran {step:g}p {0.4+ramp:.15g}n 0 {step:g}p',
                      'wrdata wave.txt '+' '.join(f'v(n{i})' for i in range(len(cap)))+' i(Vstim)',
                      'quit', '.endc', '.end']
            (folder/'deck.sp').write_text('\n'.join(lines)+'\n')
            run = subprocess.run([str(exe), '-n', '-b', 'deck.sp'], cwd=folder, capture_output=True, text=True, timeout=120,
                                 env={**os.environ, 'SPICE_SCRIPTS': str(init.resolve())})
            (folder/'ngspice.log').write_text(run.stdout+run.stderr)
            if run.returncode or re.search(r'(?im)^\s*(?:error|fatal|warning):', run.stdout+run.stderr):
                raise ValueError('SPICE diagnostic failed: '+name)
            wave = np.loadtxt(folder/'wave.txt'); t = wave[:,0]*1e9
            source50 = crossing_ns(t, wave[:,source+1], .9, edge=='rise')
            sinks = []
            for index, moment in zip(rc['sink_indices'], moments(rc, receipt['models'], edge)):
                v = wave[:,index+1]; delay = crossing_ns(t,v,.9,edge=='rise')-source50
                width = abs(crossing_ns(t,v,.36,edge=='rise')-crossing_ns(t,v,1.44,edge=='rise'))
                sinks.append(dict(delay_ps=delay*1000, slew_20_80_ps=width*1000,
                                  simple_rc_delay_ps=np.log(2)*moment*1000,
                                  difference_ps=(delay-np.log(2)*moment)*1000))
            voltage = wave[:,1:1+len(cap)]; current = -wave[:,-1]
            integrate = lambda value: cumulative_trapezoid(value, wave[:,0], axis=0, initial=0.)
            capacitance = cap*1e-12
            charge = (voltage-voltage[0]) @ capacitance
            stored = .5*(voltage**2) @ capacitance
            loss = np.zeros(len(wave))
            for conductor in rc['conductors']:
                delta = voltage[:,conductor['a']]-voltage[:,conductor['b']]
                loss += delta**2/conductor['resistance_ohm']
            supplied = integrate(voltage[:,source]*current)
            charge_error = float(np.max(abs(charge-integrate(current)))/(sum(capacitance)*1.8))
            energy_error = float(np.max(abs(stored-stored[0]+integrate(loss)-supplied))/(sum(capacitance)*1.8**2))
            negative_error = float(np.max(abs(charge+integrate(current)))/(sum(capacitance)*1.8))
            conservation = dict(charge_normalized=charge_error, energy_normalized=energy_error,
                                accepted=max(charge_error,energy_error)<1e-4,
                                reversed_source_current_rejected=negative_error>1e-4,
                                resistor_heat_j=float(integrate(loss)[-1]))
            answer['cases'].append(dict(name=name, input_receipt_sha256=digest(root/mode/'report.json'),
                                       deck_sha256=digest(folder/'deck.sp'), waveform_sha256=digest(folder/'wave.txt'),
                                       source_slew_ps=slew*1000, sinks=sinks, conservation=conservation))
            print(name, conservation, flush=True)
            (out/'report.json').write_text(json.dumps(answer, indent=2)+'\n')
answer['complete'] = True
answer['conservation_passed'] = all(c['conservation']['accepted'] and c['conservation']['reversed_source_current_rejected'] for c in answer['cases'])
(out/'report.json').write_text(json.dumps(answer, indent=2)+'\n')
