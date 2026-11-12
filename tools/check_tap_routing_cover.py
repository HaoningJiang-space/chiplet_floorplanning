"""Construct and independently replay a thermal-class routing cover."""
from collections import defaultdict
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from freeze_tap_decision_domain import physical_geometry_key
from freeze_tap_geometry import verify
from tap_global_routing import build_graph,route,verify_witness


def decode(ordinal,choices):
    indices=[]
    for options in reversed(choices):
        ordinal,remainder=divmod(ordinal,len(options));indices.append(remainder)
    if ordinal:raise ValueError('Ordinal outside domain')
    return list(reversed(indices))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--geometry',type=Path,default=Path('docs/evidence/tap-geometry-domains.json'))
    p.add_argument('--decision',type=Path,default=Path('docs/evidence/tap-decision-domain.json'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    geometry=args.geometry.read_bytes();frozen=json.loads(args.decision.read_text())
    if hashlib.sha256(geometry).hexdigest()!=frozen['domain_source_sha256']:raise ValueError('Geometry provenance mismatch')
    domain=next(c['domain'] for c in json.loads(geometry)['cases'] if c['domain']['name']==frozen['case'])
    choices=frozen['choices'];groups=defaultdict(list)
    for ordinal in frozen['geometrically_legal_mixed_radix_ordinals']:
        placement=[options[i] for options,i in zip(choices,decode(ordinal,choices))]
        verify(domain,placement);groups[physical_geometry_key(domain,placement)].append((ordinal,placement))
    if len(groups)!=frozen['thermal_distinct_count']:raise ValueError('Thermal classes mismatch')
    demands=[[int(v) for v in row] for row in domain['connection_wire_demands']]
    records=[];attempts=0
    for index,(class_key,members) in enumerate(groups.items()):
        record=dict(class_index=index,member_count=len(members),status='search_unknown',attempts=[])
        for ordinal,placement in members:
            attempts+=1
            result=route(build_graph(domain,placement),demands)
            path=args.output/f'class-{index:03d}-ordinal-{ordinal}.json.gz'
            with gzip.open(path,'wt',encoding='utf-8') as f:json.dump(dict(ordinal=ordinal,placement=placement,**result),f)
            record['attempts'].append(dict(ordinal=ordinal,status=result['status'],artifact=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            if result['status']=='verified_integer_flow_in_aggregate_resource_graph':
                # Re-read artifact, rebuild graph and verify independently of router state.
                with gzip.open(path,'rt',encoding='utf-8') as f:stored=json.load(f)
                verify(domain,stored['placement'])
                if physical_geometry_key(domain,stored['placement'])!=class_key:raise ValueError('Witness belongs to another thermal class')
                replay=verify_witness(build_graph(domain,stored['placement']),demands,stored['flows'])
                record.update(status='class_covered_by_verified_graph_witness',replay=replay)
                break
        records.append(record)
        with (args.output/'progress.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
        print(index+1,len(groups),record['status'],flush=True)
    covered=sum(r['status']=='class_covered_by_verified_graph_witness' for r in records)
    result=dict(status='aggregate_graph_zero_thermal_penalty_proved_by_class_cover' if covered==len(groups) else 'zero_penalty_unresolved',
        total_classes=len(groups),covered_classes=covered,legal_layouts=len(frozen['geometrically_legal_mixed_radix_ordinals']),
        attempts=attempts,physical_qualified=False,all_layouts_routable_claim=False,
        delta_temperature_graph_k=0 if covered==len(groups) else None,
        scope='conditional on frozen uniform-core FV thermal equivalence and aggregate resource graph; not detailed-route or measured-package evidence',
        geometry_sha256=hashlib.sha256(geometry).hexdigest(),decision_sha256=hashlib.sha256(args.decision.read_bytes()).hexdigest(),
        routing_contract_sha256=hashlib.sha256(Path('docs/tap-global-routing-contract.md').read_bytes()).hexdigest(),
        thermal_contract_sha256=hashlib.sha256(Path('docs/tap-fv-contract.md').read_bytes()).hexdigest(),classes=records)
    (args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='classes'},indent=2),flush=True)


if __name__=='__main__':main()
