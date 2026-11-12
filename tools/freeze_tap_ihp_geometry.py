"""Freeze redesigned die-envelope domains, using the existing geometry checker."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from freeze_tap_geometry import candidates,first_fit,verify as verify_geometry,box
from build_tap_ihp_endpoints import verify as verify_endpoints,source_bytes


def geometry_proxy(source, endpoint):
    # Internal rectangle-checker adapter only: its legacy 'core' fields here
    # represent the entire redesigned envelope. Never feed this proxy to thermal.
    return dict(name=source['name']+'_ihp_attachment_v1',interposer_side_um=50000,
                centre_grid_um=1000,minimum_gap_um=200,rotations_deg=[0,90,180,270],
                chiplets=[dict(id=c['id'],core_width_um=c['width_nm']//1000,
                               core_height_um=c['height_nm']//1000,bump_ring_um=0)
                          for c in endpoint['chips']])


def placed_pad(chip,placement,pad):
    x,y=pad['x_nm'],pad['y_nm'];w,h=chip['width_nm'],chip['height_nm']
    rotation=placement['rotation_deg']
    if rotation==90:x,y,w,h=h-y,x,h,w
    elif rotation==180:x,y=w-x,h-y
    elif rotation==270:x,y,w,h=y,w-x,h,w
    elif rotation!=0:raise ValueError('Unsupported rotation')
    return (placement['centre_x_um']*1000-w//2+x,
            placement['centre_y_um']*1000-h//2+y)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--endpoints',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    root=Path('local/upstream/IHP-Open-ADK')
    rules=subprocess.check_output(['git','-C',str(root),'show','093ae2e75fbc0b1eb3838a426cc1a59d37240aa0:config/rule_params.json'])
    if json.loads(rules)['rules']['ASM_b']!=200:raise ValueError('Spacing source mismatch')
    geometry_bytes=source_bytes('docs/evidence/tap-geometry-domains.json')
    evidence_bytes=source_bytes('docs/evidence/tap-ihp-endpoints.json')
    evidence=json.loads(evidence_bytes)
    if evidence['geometry_sha256']!=hashlib.sha256(geometry_bytes).hexdigest():raise ValueError('Source domain changed')
    cases=[]
    for entry,saved in zip(json.loads(geometry_bytes)['cases'],evidence['cases'],strict=True):
        source=entry['domain'];raw=(args.endpoints/saved['artifact']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=saved['sha256']:raise ValueError('Endpoint artifact changed')
        endpoint=json.loads(raw);verify_endpoints(source,endpoint)
        domain=geometry_proxy(source,endpoint)
        witness=first_fit(domain)
        if witness['status']=='geometry_feasible':
            verify_geometry(domain,witness['placement'])
            for chip,placement in zip(endpoint['chips'],witness['placement'],strict=True):
                bounds=box(domain,placement)
                for pad in chip['pads']:
                    x,y=placed_pad(chip,placement,pad)
                    if not (bounds[0]*500+25000<=x<=bounds[2]*500-25000 and bounds[1]*500+25000<=y<=bounds[3]*500-25000):
                        raise ValueError('Transformed landing outside envelope')
        cases.append(dict(case=source['name'],interposer_side_um=50000,centre_grid_um=1000,
                          minimum_gap_um=200,rotations_deg=[0,90,180,270],
                          footprints=[dict(id=c['id'],width_um=c['width_nm']//1000,height_um=c['height_nm']//1000) for c in endpoint['chips']],
                          per_chiplet_candidate_counts=[sum(1 for _ in candidates(domain,c)) for c in domain['chiplets']],
                          witness=witness))
    result=dict(status='independent_geometry_domains_frozen',physical_qualified=False,
                source_hash_convention='UTF-8 text with CRLF normalized to LF; endpoint artifact hashes use original bytes',
                endpoint_evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
                geometry_contract_sha256=hashlib.sha256(source_bytes('docs/tap-ihp-geometry-contract.md')).hexdigest(),
                adk_spacing_rules_sha256=hashlib.sha256(rules).hexdigest(),cases=cases)
    with args.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print({c['case']:c['witness']['status'] for c in cases})


if __name__=='__main__':main()
