"""Separate endpoint temperature differences from midpoint interpolation curvature."""
import argparse
import itertools
import json
from pathlib import Path
import re
import numpy as np
from chiplet_floorplanning.characterization import digest
from validation.pad_spice import crossing_ns


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('endpoints',type=Path)
    parser.add_argument('midpoint',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    roots=[args.endpoints,args.midpoint]
    reports=[json.loads((root/'report.json').read_text()) for root in roots]
    if not all(r['complete'] for r in reports):
        raise ValueError('incomplete temperature experiment')
    for field in ('netlist_sha256','executable_sha256','primitive_sources'):
        if reports[0][field]!=reports[1][field]:
            raise ValueError('temperature comparison changed '+field)
    rows={}; decks={}
    for root,report in zip(roots,reports):
        for row in report['cases']:
            key=(row['temp_c'],row['external_load_pf'],row['input_slew_ns'],row['step_ps'])
            if key in rows:
                raise ValueError('duplicate temperature case')
            folder=root/row['name']
            for filename,field in [('deck.sp','deck_sha256'),('wave.txt','waveform_sha256')]:
                if digest(folder/filename)!=row[field]:
                    raise ValueError('changed saved temperature evidence')
            wave=np.loadtxt(folder/'wave.txt'); t=wave[:,0]*1e9
            if not np.isfinite(wave).all() or np.any(np.diff(t)<=0) or t[-1]<9.99:
                raise ValueError('invalid or incomplete waveform')
            for rising,lo,hi in [(True,1.9,5.9),(False,5.9,9.9)]:
                mask=(t>=lo)&(t<=hi); times=t[mask]; v=wave[mask,1]
                actual=abs(crossing_ns(times,v,.36,rising)-crossing_ns(times,v,1.44,rising))
                if abs(actual-row['input_slew_ns'])>1e-8:
                    raise ValueError('input waveform slew changed')
                output=wave[mask,2]; edge='rise' if rising else 'fall'
                measured=dict(delay=crossing_ns(times,output,.9,rising)-crossing_ns(times,v,.9,rising),
                              slew=abs(crossing_ns(times,output,.36,rising)-crossing_ns(times,output,1.44,rising)))
                for quantity,value in measured.items():
                    if abs(value-row['metrics'][edge+'_'+quantity]['spice_ns'])>1e-10:
                        raise ValueError('reported metric does not match saved waveform')
            text='\n'.join(line.strip() for line in (folder/'deck.sp').read_text().splitlines() if line.strip())
            text=re.sub(r'(?im)^\.temp\s+[-+0-9.]+$', '.temp TEMPERATURE', text)
            text=re.sub(r'(?im)^\.include\s+"[^"]+"$', '.include SAME_HASHED_CELL', text)
            rows[key]=row; decks[key]=text
    expected=set(itertools.product((25.,62.5,100.),(.05,.232079),(.223607,),(1.,2.)))
    if set(rows)!=expected:
        raise ValueError('experiment does not cover the declared temperature/load/step domain')
    result=dict(source_sha256=digest(__file__),input_sha256={str(root/'report.json'):digest(root/'report.json') for root in roots},
                physical_qualified=False, scope='two-load buf_8 schematic diagnostic; no production slack or physical error bound', rows=[])
    for load,step in itertools.product((.05,.232079),(1.,2.)):
        keys=[(t,load,.223607,step) for t in (25.,62.5,100.)]
        if len({decks[k] for k in keys})!=1:
            raise ValueError('decks differ beyond temperature and identical cell include path')
        a,m,b=[rows[k]['metrics'] for k in keys]
        for metric in a:
            spice_delta=(b[metric]['spice_ns']-a[metric]['spice_ns'])*1000
            liberty_delta=(b[metric]['liberty_ns']-a[metric]['liberty_ns'])*1000
            curvature=(m[metric]['spice_ns']-(a[metric]['spice_ns']+b[metric]['spice_ns'])/2)*1000
            result['rows'].append(dict(load_pf=load,step_ps=step,metric=metric,spice_delta_25_100_ps=spice_delta,
                liberty_delta_25_100_ps=liberty_delta,delta_discrepancy_ps=spice_delta-liberty_delta,
                spice_midpoint_curvature_ps=curvature))
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('Verified',len(rows),'temperature cases;',len(result['rows']),'differential observations')


if __name__=='__main__':
    main()
