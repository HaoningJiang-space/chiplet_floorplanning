"""Same-cell-revision core diagnostic; primitive/PEX characterization match unproven."""
import argparse
import os, json, sys, subprocess, re
from pathlib import Path
from urllib.request import urlopen
import numpy as np
from scipy.interpolate import RegularGridInterpolator

from validation.pad_sources import prepare
from validation.pad_spice import crossing_ns
from chiplet_floorplanning.characterization import digest

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--restore-stress-geometry',action='store_true')
    args=parser.parse_args()
    out=args.output; out.mkdir(exist_ok=False)
    primitive=prepare(Path('local/pad-spice'))
    url='https://raw.githubusercontent.com/google/skywater-pdk-libs-sky130_fd_sc_hd/ac7fb61f06e6470b94e8afdf7c25268f62fbd7b1/cells/buf/sky130_fd_sc_hd__buf_8.spice'
    raw=urlopen(url,timeout=30).read()
    original=out/'buf_8_original.spice'; original.write_bytes(raw)
    if digest(original)!='98bafb7bbd4aa107e9b0090ee241f30a6a84aa5b394bb8eaca5b189a207cd5c7':
        raise ValueError('pinned core netlist hash mismatch')
    cdl=out/'buf_8.cdl'; cdl.write_bytes(urlopen(url.replace('.spice','.cdl'),timeout=30).read())
    if cdl.read_text().count('sa=0.265')!=4 or cdl.read_text().count('sb=0.265 sd=0.28')!=4:
        raise ValueError('unexpected source stress geometry')
    net=out/'buf_8.spice'
    if args.restore_stress_geometry:
        text='\n'.join(line+' sa=265000u sb=265000u sd=280000u' if line.startswith('X') else line for line in raw.decode().splitlines())+'\n'
        net.write_text(text)
    else:
        net.write_bytes(raw)
    init=out/'empty-init'; init.mkdir(); (init/'spinit').write_text('* explicit transistor models only\n')
    exe=Path('local/ngspice-42-msys2/ucrt64/bin/ngspice_con.exe').resolve()
    lib=Path('local/pad-spice/sky130A/libs.tech/ngspice/sky130.lib.spice').resolve()
    report=dict(complete=False,source_sha256=digest(__file__),netlist_url=url,netlist_sha256=digest(net),
                primitive_sources=primitive,executable_sha256=digest(exe),physical_qualified=False, original_netlist_sha256=digest(original), cdl_sha256=digest(cdl), restore_stress_geometry=args.restore_stress_geometry, cases=[])
    for temp in (25,100):
        library=Path(f'local/pdk-v03/sky_buf_8_tt_{temp:03d}C_1v80.json')
        tables=json.loads(library.read_text())['pin,X']['timing']
        # Two exact load knots per temperature; eliminate load/slew interpolation as a confounder.
        tab=tables['cell_rise,del_1_7_7']; slew=tab['index_1'][3]
        for load in tab['index_2'][3:5]:
            for step in (2.,1.):
                name=f't{temp}_c{load}_dt{step:g}'; folder=out/name; folder.mkdir()
                ramp=slew/.6
                deck=f'''Same-revision buf_8 diagnostic, not qualified characterization
    .lib "{lib.as_posix()}" tt
    .include "{net.resolve().as_posix()}"
    .options scale=1u reltol=1e-6 abstol=1e-13 vntol=1e-8
    .temp {temp}
    VDD vdd 0 1.8
    VIN vin 0 PWL(0 0 2n 0 {2+ramp}n 1.8 6n 1.8 {6+ramp}n 0 10n 0)
    Xbuf vin 0 0 vdd vdd out sky130_fd_sc_hd__buf_8
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
                for edge,start,stop in [('rise',1.9,5.9),('fall',5.9,9.9)]:
                    mask=(t>=start)&(t<=stop); times=t[mask]; a,b=data[mask,1],data[mask,2]; rising=edge=='rise'
                    delay=crossing_ns(times,b,.9,rising)-crossing_ns(times,a,.9,rising)
                    transition=abs(crossing_ns(times,b,.36,rising)-crossing_ns(times,b,1.44,rising))
                    for quantity,value,key in [('delay',delay,'cell_'+edge),('slew',transition,edge+'_transition')]:
                        table=tables[key+',del_1_7_7']
                        reference=float(RegularGridInterpolator((table['index_1'],table['index_2']),table['values'],bounds_error=True)([[slew,load]])[0])
                        measured[edge+'_'+quantity]=dict(spice_ns=value,liberty_ns=reference,difference_ps=(value-reference)*1000)
                report['cases'].append(dict(name=name,temp_c=temp,input_slew_ns=slew,external_load_pf=load,step_ps=step,
                    known_library_warning=known_warning if known_warning in log else None, library_sha256=digest(library),deck_sha256=digest(folder/'deck.sp'),waveform_sha256=digest(folder/'wave.txt'),metrics=measured))
                print(name,measured,flush=True)
                (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    report['complete']=True
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
