"""Same-cell-revision core diagnostic; primitive/PEX characterization match unproven."""
import argparse
import os, json, sys, subprocess, re
from pathlib import Path
from urllib.request import urlopen
import numpy as np
from scipy.interpolate import RegularGridInterpolator

from validation.pad_sources import prepare
from validation.pad_spice import crossing_ns
from chiplet_floorplanning.characterization import digest, interpolate_cell

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--restore-stress-geometry',action='store_true')
    parser.add_argument('--temperatures',type=float,nargs='+',default=[25.,100.])
    parser.add_argument('--cell',choices=('buf_8','inv_1'),default='buf_8')
    args=parser.parse_args()
    if args.restore_stress_geometry and args.cell!='buf_8':
        raise ValueError('stress-geometry counterfactual is declared only for buf_8')
    if len(set(args.temperatures))!=len(args.temperatures) or any(not 25<=t<=100 for t in args.temperatures):
        raise ValueError('unique temperatures within the 25..100 C bracket required')
    out=args.output; out.mkdir(exist_ok=False)
    primitive=prepare(Path('local/pad-spice'))
    family=args.cell.split('_')[0]
    url=f'https://raw.githubusercontent.com/google/skywater-pdk-libs-sky130_fd_sc_hd/ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1/cells/{family}/sky130_fd_sc_hd__{args.cell}.spice'
    raw=urlopen(url,timeout=30).read()
    original=out/(args.cell+'_original.spice'); original.write_bytes(raw)
    hashes={'buf_8':'98bafb7bbd4aa107e9b0090ee241f30a6a84aa5b394bb8eaca5b189a207cd5c7',
            'inv_1':'1099e3641c46d241852db47974540b3ad161e20e01b74f2fd5cc152627011909'}
    if digest(original)!=hashes[args.cell]:
        raise ValueError('pinned core netlist hash mismatch')
    cdl=out/(args.cell+'.cdl'); cdl.write_bytes(urlopen(url.replace('.spice','.cdl'),timeout=30).read())
    if args.restore_stress_geometry and (cdl.read_text().count('sa=0.265')!=4 or cdl.read_text().count('sb=0.265 sd=0.28')!=4):
        raise ValueError('unexpected source stress geometry')
    net=out/(args.cell+'.spice')
    if args.restore_stress_geometry:
        text='\n'.join(line+' sa=265000u sb=265000u sd=280000u' if line.startswith('X') else line for line in raw.decode().splitlines())+'\n'
        net.write_text(text)
    else:
        net.write_bytes(raw)
    init=out/'empty-init'; init.mkdir(); (init/'spinit').write_text('* explicit transistor models only\n')
    exe=Path('local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe').resolve()
    lib=Path('local/pad-spice/sky130A/libs.tech/ngspice/sky130.lib.spice').resolve()
    report=dict(complete=False,cell=args.cell,source_sha256=digest(__file__),netlist_url=url,netlist_sha256=digest(net),
                primitive_sources=primitive,executable_sha256=digest(exe),physical_qualified=False, original_netlist_sha256=digest(original), cdl_sha256=digest(cdl), restore_stress_geometry=args.restore_stress_geometry, cases=[])
    libraries=[Path(f'local/pdk-v03/sky_{args.cell}_tt_{t:03d}C_1v80.json') for t in (25,100)]
    endpoints=[json.loads(p.read_text()) for p in libraries]
    output_pin='X' if args.cell=='buf_8' else 'Y'
    reference=endpoints[0]['pin,'+output_pin]['timing']['cell_rise,del_1_7_7']
    slew=reference['index_1'][3]; loads=reference['index_2'][3:5]
    report['declared_stimulus']=dict(input_slew_ns=slew,external_loads_pf=loads,steps_ps=[2.,1.],
        policy='fixed_25C_knots_bounded_queries_at_other_temperatures')
    for temp in args.temperatures:
        tables=interpolate_cell(*endpoints,(temp-25)/75)['pin,'+output_pin]['timing']
        if tables['timing_sense']!=('positive_unate' if args.cell=='buf_8' else 'negative_unate'):
            raise ValueError('unexpected cell edge semantics')
        # Hold physical stimuli fixed; other temperatures may require bounded interpolation.
        for load in loads:
            for step in (2.,1.):
                name=f't{temp}_c{load}_dt{step:g}'; folder=out/name; folder.mkdir()
                ramp=slew/.6
                deck=f'''Same-revision {args.cell} diagnostic, not qualified characterization
    .lib "{lib.as_posix()}" tt
    .include "{net.resolve().as_posix()}"
    .options scale=1u reltol=1e-6 abstol=1e-13 vntol=1e-8
    .temp {temp}
    VDD vdd 0 1.8
    VIN vin 0 PWL(0 0 2n 0 {2+ramp}n 1.8 6n 1.8 {6+ramp}n 0 10n 0)
    Xbuf vin 0 0 vdd vdd out sky130_fd_sc_hd__{args.cell}
    Cload out 0 {load}p
    .control
    set numdgt=15
    set wr_singlescale
    tran {step}p 10n 0 {step}p
    wrdata wave.txt v(vin) v(out) i(VDD) i(VIN)
    quit
    .endc
    .end
    '''
                (folder/'deck.sp').write_text(deck)
                run=subprocess.run([str(exe),'-n','-D','ngbehavior=hsa','-b','deck.sp'],cwd=folder,
                    capture_output=True,text=True,timeout=120,env={**os.environ,'SPICE_SCRIPTS':str(init.resolve())})
                log=run.stdout+run.stderr; (folder/'ngspice.log').write_text(log)
                known_warning='Warning: m=xx on .subckt line will override multiplier m hierarchy!'
                screened_log=log.replace(known_warning,'')
                if run.returncode or re.search(r'(?im)^\s*(?:error|fatal|warning):',screened_log):
                    raise ValueError('unadmitted simulator log '+name)
                data=np.loadtxt(folder/'wave.txt'); t=data[:,0]*1e9; measured={}
                for input_edge,start,stop in [('rise',1.9,5.9),('fall',5.9,9.9)]:
                    edge=input_edge if args.cell=='buf_8' else ('fall' if input_edge=='rise' else 'rise')
                    mask=(t>=start)&(t<=stop); times=t[mask]; a,b=data[mask,1],data[mask,2]; rising=edge=='rise'
                    delay=crossing_ns(times,b,.9,rising)-crossing_ns(times,a,.9,input_edge=='rise')
                    transition=abs(crossing_ns(times,b,.36,rising)-crossing_ns(times,b,1.44,rising))
                    for quantity,value,key in [('delay',delay,'cell_'+edge),('slew',transition,edge+'_transition')]:
                        table=tables[key+',del_1_7_7']
                        reference=float(RegularGridInterpolator((table['index_1'],table['index_2']),table['values'],bounds_error=True)([[slew,load]])[0])
                        measured[edge+'_'+quantity]=dict(spice_ns=value,liberty_ns=reference,difference_ps=(value-reference)*1000)
                report['cases'].append(dict(name=name,temp_c=temp,input_slew_ns=slew,external_load_pf=load,step_ps=step,
                    known_library_warning=known_warning if known_warning in log else None,
                    library_source_sha256={str(p):digest(p) for p in libraries},
                    temperature_interpolated=temp not in (25,100),
                    deck_sha256=digest(folder/'deck.sp'),waveform_sha256=digest(folder/'wave.txt'),metrics=measured))
                print(name,measured,flush=True)
                (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    report['complete']=True
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
