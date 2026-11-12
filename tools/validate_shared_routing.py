"""Local finite-track routing, shared-clock ownership and infeasibility proofs."""

import argparse
from dataclasses import asdict,is_dataclass
from pathlib import Path
from time import perf_counter

from chiplet_floorplanning.routing_graph import Fabric,Net,audit,cut_certificate,verify_cut,route_greedy
from validation.measured_sources import digest
from validation.sources import git_revision,write_json
from validation.routing_exhaustive import enumerate_assignments
from validation.shared_routing_fixture import scalable,shared_bottleneck,greedy_counterexample


def clean(value):
    if is_dataclass(value):
        return clean(asdict(value))
    if isinstance(value,dict):
        return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(set,frozenset)):
        return [clean(v) for v in sorted(value)]
    if isinstance(value,(tuple,list)):
        return [clean(v) for v in value]
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    sources=[Path(__file__),Path('src/chiplet_floorplanning/routing_graph.py'),
        Path('tools/validation/routing_exhaustive.py'),Path('tools/validation/shared_routing_fixture.py'),Path('docs/shared-routing-plan.md')]
    report=dict(git=git_revision(Path('.')),code_sha256={str(p):digest(p) for p in sources},cases={},checks={},
                physical_package_qualified=False,complete=False)
    write_json(args.output/'frozen-inputs.json',report)
    for receivers in (1,3,7,15):
        for blocked in (False,True):
            name=f'chiplets_{receivers+1}_'+('capacity_shortfall' if blocked else 'feasible')
            fabric,nets=scalable(receivers,blocked_clock=blocked)
            start=perf_counter();greedy=route_greedy(fabric,nets);elapsed=perf_counter()-start
            certificate=cut_certificate(fabric,nets,3)
            verified=verify_cut(fabric,nets,certificate)
            report['cases'][name]=dict(fabric=fabric,nets=nets,greedy=greedy,route_time_s=elapsed,
                                      certificate=certificate,certificate_verified_infeasible=verified)
            report['checks'][name]=verified if blocked else greedy['status']=='feasible' and not verified
            print(name,greedy['status'],'cut',certificate['demand'],certificate['capacity'],flush=True)
    fabric,nets,routes=shared_bottleneck()
    exact=enumerate_assignments(fabric,nets)
    result=audit(fabric,nets,routes)
    certificate=cut_certificate(fabric,nets,1)
    report['cases']['shared_clock_single_slot']=dict(fabric=fabric,nets=nets,routes=routes,audit=result,exact=exact,certificate=certificate)
    report['checks']['shared_clock_single_slot']=bool(result['fabric_legal'] and exact['status']=='feasible' and certificate['demand']==certificate['capacity']==1)
    fabric,nets=greedy_counterexample()
    greedy=route_greedy(fabric,nets);exact=enumerate_assignments(fabric,nets)
    report['cases']['greedy_counterexample']=dict(fabric=fabric,nets=nets,greedy=greedy,exact=exact,
                                                witness_audit=audit(fabric,nets,exact['routes']))
    report['checks']['greedy_is_not_proof']=bool(greedy['status']=='search_failed' and not greedy['proven_infeasible'] and exact['status']=='feasible' and report['cases']['greedy_counterexample']['witness_audit']['fabric_legal'])
    fabric=Fabric(3,3)
    nets=(Net('a','data',(0,1,0),((2,1,0),)),Net('b','data',(1,0,0),((1,2,0),)))
    exact=enumerate_assignments(fabric,nets)
    limited=enumerate_assignments(fabric,nets,max_states=1)
    report['cases']['crossing_exhaustive']=dict(fabric=fabric,nets=nets,exact=exact,limited=limited)
    report['checks']['exhaustive_crossing']=exact['proven_infeasible'] and exact['status']=='exhaustive_infeasible'
    report['checks']['enumeration_limit_is_unknown']=not limited['proven_infeasible'] and limited['status']=='exhaustive_limit'
    report.update(complete=True,numerical_checks_passed=all(report['checks'].values()))
    write_json(args.output/'report.json',clean(report))
    print('checks',report['checks'])
    return 0 if report['numerical_checks_passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
