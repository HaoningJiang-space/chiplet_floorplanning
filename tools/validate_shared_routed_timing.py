"""One physical routed tree -> SPEF -> complete multi-lane OpenSTA paths."""

import argparse
import copy
from dataclasses import asdict
import json
from pathlib import Path
import re
import subprocess

from chiplet_floorplanning.routing_graph import route_greedy
from validation.shared_routing_fixture import scalable
from validation.shared_routing_electrical import package_spef,SPEF_HEADER,spef_tree
from validation.multilane_oracle import Network
from validation.multilane_fixture import libraries,netlist,script
from validation.multilane_report import extract
from validation.timing_report import NUMBER
from validation.measured_sources import digest
from validation.sources import git_revision,write_json
from validate_multilane_timing import compare
from validate_shared_routing import clean


def check_annotation(log,records):
    errors=[]
    for name,rc in records.items():
        matches=re.findall(rf'RC_BEGIN {name}\n(.*?)RC_END {name}',log,re.S)
        if len(matches)!=1:
            raise ValueError('missing unique conductor annotation report')
        block=matches[0]
        for label,value in (('Wire capacitance',rc['total_parasitic_pf']),
                            ('Pin capacitance',rc['total_sink_pin_pf']),
                            ('Total capacitance',rc['total_parasitic_pf']+rc['total_sink_pin_pf'])):
            found=re.findall(rf'{label}:\s*({NUMBER})',block)
            if len(found)!=1:
                raise ValueError('missing unique conductor capacitance')
            errors.append(abs(float(found[0])-value))
        if not re.search(r'Number of drivers:\s+1\b',block) or not re.search(rf'Number of loads:\s+{len(rc["sink_indices"])}\b',block):
            raise ValueError('shared clock driver/load ownership mismatch')
    if max(errors)>1e-6:
        raise ValueError('routed capacitance differs from unique physical conductor sum')
    return max(errors)


def compare_channels(paths,c,records,correlated=False):
    adjusted=copy.deepcopy(paths);wire_rows=[]
    for key,actual in paths.items():
        receiver,lane,check,_=key.split('_');receiver=int(receiver)
        data=records['data_'+str(receiver)+'_'+lane];clock=records['forwarded_clock']
        dd=data['single_pole_50pct_delay_ns'][0];dc=clock['single_pole_50pct_delay_ns'][receiver]
        normalized=adjusted[key]
        normalized['data_arrival_ns']-=dd
        normalized['capture_arrival_ns']-=dc
        normalized['required_ns']-=dc
        normalized['slack_ns']-=dc-dd if check=='setup' else dd-dc
        normalized['pins']['data']['cap_pf']-=data['total_parasitic_pf']
        normalized['pins']['trunk']['cap_pf']-=clock['total_parasitic_pf']
        for label,pin,driver,rc,index in (
            ('data','receive_d','data',data,0),('clock','branch_input','trunk',clock,receiver)):
            expected_delay=rc['single_pole_50pct_delay_ns'][index]
            expected_slew=.1+rc['single_pole_20_80_slew_increment_ns'][index]
            # The report contains float32 absolute path times. Small differences
            # can be below that arithmetic resolution despite nine print digits.
            resolution=max(1e-9,4*2**-23*max(abs(actual['pins'][pin]['time_ns']),abs(actual['pins'][driver]['time_ns']),1.))
            error=abs(actual['pins'][pin]['delay_ns']-expected_delay)
            slew_error=abs(actual['pins'][pin]['slew_ns']-expected_slew)
            if error>resolution or slew_error>1e-7:
                raise ValueError(f'{key}: independent RC channel moment mismatch ({error}, {slew_error})')
            wire_rows.append(dict(path=key,channel=label,expected_delay_ns=expected_delay,
                reported_delay_ns=actual['pins'][pin]['delay_ns'],delay_error_ns=error,
                report_resolution_ns=resolution,delay_resolved=expected_delay>resolution,slew_error_ns=slew_error))
    result=compare(adjusted,c,correlated,correlated)
    # Algebraically remove the independently computed wire terms only to reuse
    # the fixed cell/clock audit. This is not a fitted correction to STA results.
    result['channel_checks']=wire_rows
    result['comparison_coordinates']='paths.normalized_observed removes independently computed wire terms for the fixed-cell/clock audit; routed_observed retains raw reported path times'
    result['routed_observed']={key:{name:value for name,value in row.items() if name!='pins'} for key,row in paths.items()}
    result['max_channel_delay_error_ns']=max(r['delay_error_ns'] for r in wire_rows)
    result['max_channel_slew_error_ns']=max(r['slew_error_ns'] for r in wire_rows)
    result['unresolved_channel_delay_observations']=sum(not r['delay_resolved'] for r in wire_rows)
    result['wire_model']='declared_single_pole_of_exact_RC_first_moment_not_exact_distributed_waveform'
    return result


def run(sta,folder,receivers,scale=1.,correlated=False,mutation=None):
    folder.mkdir();fabric,nets=scalable(receivers)
    routed=route_greedy(fabric,nets)
    if routed['status']!='feasible':
        raise ValueError('cannot perform timing on unrouted design')
    spef,records=package_spef(fabric,nets,routed['routes'],scale)
    if mutation:
        spef=SPEF_HEADER
        for name,record in records.items():
            changed=copy.deepcopy(record)
            if name=='forwarded_clock':
                if mutation=='missing_clock_parasitics':
                    continue
                if mutation=='doubled_clock_capacitance':
                    changed['node_parasitic_pf']=[2*x for x in changed['node_parasitic_pf']]
                    changed['total_parasitic_pf']*=2
            spef+=spef_tree(changed['design_net'],changed['source_pin'],changed['sink_pins'],changed)
    c=Network(receivers=receivers)
    annotation='read_spef package.spef\n'
    for name,record in records.items():
        annotation+=f'puts "RC_BEGIN {name}"\nreport_net -connections -verbose -digits 9 {record["design_net"]}\nputs "RC_END {name}"\n'
    tcl=script(c,correlated,correlated).replace('link_design fabric\n','link_design fabric\nset_delay_calculator simple_rc\n')
    tcl=tcl.replace('puts "NETWORK_CHECKS_BEGIN"',annotation+'puts "NETWORK_CHECKS_BEGIN"')
    tcl=tcl.replace('-fields {slew cap} -digits 6','-fields {slew cap input_pin} -digits 9')
    files={'fixture.lib':libraries(c),'fabric.v':netlist(c),'package.spef':spef,'run.tcl':tcl}
    if correlated:
        files['early.lib']=libraries(c,True)
    hashes={}
    for name,text in files.items():
        path=folder/name;path.write_bytes(text.encode('utf-8'));hashes[name]=digest(path)
    write_json(folder/'routing.json',clean(dict(fabric=fabric,nets=nets,routed=routed)))
    write_json(folder/'rc-reference.json',records)
    execution=subprocess.run([str(sta),'-no_init','-exit','run.tcl'],cwd=folder,capture_output=True,text=True,timeout=120)
    log=execution.stdout+execution.stderr;(folder/'sta.log').write_text(log)
    result=dict(model=asdict(c),resistance_scale=scale,correlated_root=correlated,mutation=mutation,
        returncode=execution.returncode,input_sha256=hashes,log_sha256=digest(folder/'sta.log'),
        routing_sha256=digest(folder/'routing.json'),rc_reference_sha256=digest(folder/'rc-reference.json'),
        physical_package_qualified=False,physical_channel_qualified=False)
    try:
        if execution.returncode:
            raise ValueError('STA execution failed')
        result['max_annotation_capacitance_error_pf']=check_annotation(log,records)
        result.update(compare_channels(extract(log,c.receivers,c.lanes,True),c,records,correlated))
        result['numerical_contract_accepted']=True
    except ValueError as error:
        result.update(numerical_contract_accepted=False,rejection_reason=str(error))
    write_json(folder/'receipt.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sta',type=Path,default=Path('local/upstream/OpenSTA/app/sta.exe'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False);sta=args.sta.resolve(strict=True)
    paths=[Path(__file__),Path('tools/validate_multilane_timing.py'),Path('tools/validate_shared_routing.py'),
        Path('src/chiplet_floorplanning/routing_graph.py'),Path('tools/validation/shared_routing_electrical.py'),
        Path('tools/validation/shared_routing_fixture.py'),Path('tools/validation/timing_fixture.py'),
        Path('tools/validation/timing_oracle.py'),Path('tools/validation/timing_report.py'),Path('docs/shared-routing-plan.md')]+list(Path('tools/validation').glob('multilane_*.py'))
    report=dict(git=git_revision(Path('.')),code_sha256={str(p):digest(p) for p in paths},executable_sha256=digest(sta),
                cases={},negative_controls={},complete=False,physical_package_qualified=False,physical_channel_qualified=False)
    write_json(args.output/'frozen-inputs.json',report)
    specs=[(n,1.,False) for n in (1,3,7,15)]+[(n,100.,False) for n in (1,15)]+[(15,1.,True)]
    for receivers,scale,correlated in specs:
        name=f'chiplets_{receivers+1}_r{int(scale)}'+('_correlated' if correlated else '')
        report['cases'][name]=run(sta,args.output/name,receivers,scale,correlated)
        write_json(args.output/'report.json',report)
        print(name,report['cases'][name]['numerical_contract_accepted'],report['cases'][name].get('rejection_reason'),flush=True)
    for mutation in ('missing_clock_parasitics','doubled_clock_capacitance'):
        report['negative_controls'][mutation]=run(sta,args.output/mutation,3,mutation=mutation)
    checks={k:v['numerical_contract_accepted'] for k,v in report['cases'].items()}
    checks.update({'reject_'+k:not v['numerical_contract_accepted'] for k,v in report['negative_controls'].items()})
    report.update(complete=True,checks=checks,numerical_checks_passed=all(checks.values()))
    write_json(args.output/'report.json',report)
    print(json.dumps(checks,indent=2))
    return 0 if all(checks.values()) else 1


if __name__=='__main__':
    raise SystemExit(main())
