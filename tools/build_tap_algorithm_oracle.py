"""Local HiTS oracle for the already-frozen exact six-chip decision domain."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from build_tap_ihp_endpoints import source_bytes
from freeze_tap_geometry import verify
from prepare_tap_fv import make_case
from solve_tap_fv_hits import run
from chiplet_floorplanning.model import parse_case


def centre_span(domain,placement):
    by_id={p['id']:p for p in placement};total=0.;demand=0.
    for s,row in enumerate(domain['connection_wire_demands']):
        for t,amount in enumerate(row):
            a,b=by_id[s],by_id[t]
            total+=amount*(abs(a['centre_x_um']-b['centre_x_um'])+abs(a['centre_y_um']-b['centre_y_um']))/1000
            demand+=amount
    return total/demand


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hits',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    raw=source_bytes('docs/evidence/tap-decision-domain.json');frozen=json.loads(raw)
    geometry=source_bytes('docs/evidence/tap-geometry-domains.json')
    domain=next(c['domain'] for c in json.loads(geometry)['cases'] if c['domain']['name']==frozen['case'])
    rows=[];started=time.perf_counter()
    for index,group in enumerate(frozen['thermal_equivalence_classes']):
        placement=[options[i] for options,i in zip(frozen['choices'],group['representative'],strict=True)]
        verify(domain,placement);data=make_case(domain,placement)
        summary,_,_,_=run(parse_case(data),args.hits)
        row=dict(class_index=index,placement=placement,thermal=summary,
                 centre_span_mm=centre_span(domain,placement))
        path=args.output/f'class-{index:03d}.json'
        path.write_text(json.dumps(row,indent=2),encoding='utf-8')
        rows.append(row)
        print(index,summary['peak_power_layer_c'],row['centre_span_mm'],flush=True)
        if not summary['numerical_admission_passed']:raise ValueError(f'Class {index} thermal admission failed')
    result=dict(status='complete_finite_domain_oracle',case=frozen['case'],classes=len(rows),
                decision_domain_sha256=hashlib.sha256(raw).hexdigest(),
                geometry_sha256=hashlib.sha256(geometry).hexdigest(),
                plan_sha256=hashlib.sha256(source_bytes('docs/tap-algorithm-reference-plan.md')).hexdigest(),
                elapsed_seconds=time.perf_counter()-started,physical_optimum_certified=False,
                rows=[dict(class_index=r['class_index'],placement=r['placement'],
                           peak_c=r['thermal']['peak_power_layer_c'],ambient_c=45,
                           centre_span_mm=r['centre_span_mm'],
                           residual=r['thermal']['original_relative_residual'],
                           max_reference_difference_k=r['thermal']['max_reference_difference_k'],
                           thermal_admitted=r['thermal']['numerical_admission_passed']) for r in rows])
    (args.output/'oracle.json').write_text(json.dumps(result,indent=2),encoding='utf-8')


if __name__=='__main__':main()
