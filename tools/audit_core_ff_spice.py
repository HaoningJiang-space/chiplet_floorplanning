"""Fixed-stimulus clock-to-Q diagnostic; not setup/hold characterization."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.request import urlopen

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from chiplet_floorplanning.characterization import digest, interpolate_cell
from validation.pad_sources import prepare
from validation.pad_spice import crossing_ns, subcircuits


def measure(data):
    """Require initialized low Q, then exactly one captured rise and fall."""
    if data.ndim != 2 or data.shape[1] != 7 or not np.isfinite(data).all():
        raise ValueError('invalid waveform columns')
    time = data[:, 0] * 1e9
    if np.any(np.diff(time) <= 0) or time[0] > .01 or time[-1] < 17.999:
        raise ValueError('incomplete or nonmonotonic waveform')
    for start, stop, target in ((3., 3.5, 0.), (9., 9.5, 1.8), (15., 15.5, 0.)):
        values = data[(time >= start) & (time <= stop), 3]
        if len(values) == 0 or np.max(abs(values-target)) > .018:
            raise ValueError('failed stable capture')
    result = {}
    for edge, start in (('rise', 7.), ('fall', 13.)):
        mask = (time >= start-.05) & (time <= start+1.9)
        t, clk, q = time[mask], data[mask, 1], data[mask, 3]
        rising = edge == 'rise'
        result[edge+'_delay_ns'] = crossing_ns(t, q, .9, rising)-crossing_ns(t, clk, .9, True)
        result[edge+'_slew_ns'] = abs(crossing_ns(t, q, 1.44, rising)-crossing_ns(t, q, .36, rising))
        result[edge+'_clock_slew_ns'] = crossing_ns(t, clk, 1.44, True)-crossing_ns(t, clk, .36, True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    out.mkdir(exist_ok=False)
    primitive = prepare(Path('local/pad-spice'))
    url = ('https://raw.githubusercontent.com/google/skywater-pdk-libs-sky130_fd_sc_hd/'
           'ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1/cells/dfxtp/sky130_fd_sc_hd__dfxtp_1.spice')
    net = out/'dfxtp_1.spice'
    net.write_bytes(urlopen(url, timeout=30).read())
    if digest(net) != '39049c3c6a74ac24fdc0d93528dd5b0e15f7ef51729008913bdeeee0d8ead2df':
        raise ValueError('pinned netlist mismatch')
    if subcircuits(net.read_text())['sky130_fd_sc_hd__dfxtp_1']['pins'] != ['CLK', 'D', 'VGND', 'VNB', 'VPB', 'VPWR', 'Q']:
        raise ValueError('unexpected pin order')
    libraries = [Path(f'local/pdk-v03/sky_dfxtp_1_tt_{t:03d}C_1v80.json') for t in (25, 100)]
    endpoints = [json.loads(p.read_text()) for p in libraries]
    for endpoint in endpoints:
        arc = endpoint['pin,Q']['timing']
        if endpoint['ff,IQ,IQ_N'] != {'clocked_on': 'CLK', 'next_state': 'D'} or arc['timing_type'] != 'rising_edge' or arc['related_pin'] != 'CLK':
            raise ValueError('unexpected sequential semantics')
    reference = endpoints[0]['pin,Q']['timing']['cell_rise,del_1_7_7']
    slew, loads = reference['index_1'][3], reference['index_2'][3:5]
    ramp = slew/.6
    exe = Path('local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe').resolve()
    model = Path('local/pad-spice/sky130A/libs.tech/ngspice/sky130.lib.spice').resolve()
    init = out/'empty-init'
    init.mkdir()
    (init/'spinit').write_text('* explicit transistor models only\n')
    report = dict(complete=False, physical_qualified=False, cell='dfxtp_1',
                  scope='clock-to-Q only; primitive/PEX characterization identity unresolved',
                  source_sha256=digest(__file__), netlist_url=url, netlist_sha256=digest(net),
                  primitive_sources=primitive, executable_sha256=digest(exe),
                  library_source_sha256={str(p): digest(p) for p in libraries},
                  declared_stimulus=dict(supply_v=1.8, clock_and_data_slew_ns=slew,
                      external_loads_pf=loads, steps_ps=[2., 1.], data_advance_ns=[2., 3.],
                      temperatures_c=[25., 62.5, 100.], thresholds_pct=[20, 50, 80]), cases=[])
    for temp in (25., 62.5, 100.):
        tables = interpolate_cell(*endpoints, (temp-25)/75)['pin,Q']['timing']
        for load in loads:
            for advance in (2., 3.):
                for step in (2., 1.):
                    name = f't{temp}_c{load}_advance{advance}_dt{step}'
                    folder = out/name
                    folder.mkdir()
                    # Initial clock captures zero. Subsequent rising clocks capture 1, then 0.
                    clock = '0 0 '
                    for start in (1., 7., 13.):
                        clock += f'{start}n 0 {start+ramp}n 1.8 {start+2}n 1.8 {start+2+ramp}n 0 '
                    clock += '18n 0'
                    deck = f'''Clock-to-Q diagnostic, not qualified characterization
.lib "{model.as_posix()}" tt
.include "{net.resolve().as_posix()}"
.options scale=1u reltol=1e-6 abstol=1e-13 vntol=1e-8
.temp {temp}
VDD vdd 0 1.8
VCLK clk 0 PWL({clock})
VD d 0 PWL(0 0 {7-advance}n 0 {7-advance+ramp}n 1.8 {13-advance}n 1.8 {13-advance+ramp}n 0 18n 0)
Xff clk d 0 0 vdd vdd q sky130_fd_sc_hd__dfxtp_1
Cload q 0 {load}p
.control
set numdgt=15
set wr_singlescale
tran {step}p 18n 0 {step}p
wrdata wave.txt v(clk) v(d) v(q) i(VDD) i(VCLK) i(VD)
quit
.endc
.end
'''
                    (folder/'deck.sp').write_text(deck)
                    run = subprocess.run([str(exe), '-n', '-D', 'ngbehavior=hsa', '-b', 'deck.sp'],
                        cwd=folder, capture_output=True, text=True, timeout=120,
                        env={**os.environ, 'SPICE_SCRIPTS': str(init.resolve())})
                    log = run.stdout+run.stderr
                    (folder/'ngspice.log').write_text(log)
                    known = 'Warning: m=xx on .subckt line will override multiplier m hierarchy!'
                    if run.returncode or re.search(r'(?im)^\s*(?:error|fatal|warning):', log.replace(known, '')):
                        raise ValueError('unadmitted simulator log '+name)
                    metrics = measure(np.loadtxt(folder/'wave.txt'))
                    comparisons = {}
                    for edge in ('rise', 'fall'):
                        if abs(metrics[edge+'_clock_slew_ns']-slew) > 1e-8:
                            raise ValueError('clock stimulus differs from declared slew')
                        for quantity, table_name in (('delay', 'cell_'+edge), ('slew', edge+'_transition')):
                            table = tables[table_name+',del_1_7_7']
                            predicted = float(RegularGridInterpolator((table['index_1'], table['index_2']),
                                table['values'], bounds_error=True)([[slew, load]])[0])
                            actual = metrics[edge+'_'+quantity+'_ns']
                            comparisons[edge+'_'+quantity] = dict(spice_ns=actual, liberty_ns=predicted,
                                difference_ps=(actual-predicted)*1000)
                    report['cases'].append(dict(name=name, temp_c=temp, external_load_pf=load,
                        data_advance_ns=advance, step_ps=step, metrics=comparisons,
                        known_library_warning=known if known in log else None,
                        artifacts_sha256={f: digest(folder/f) for f in ('deck.sp', 'wave.txt', 'ngspice.log')}))
                    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
                    print(name, flush=True)
    report['complete'] = True
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
