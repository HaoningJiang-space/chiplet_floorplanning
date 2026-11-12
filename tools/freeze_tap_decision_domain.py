"""Freeze an exact finite six-chip domain and honest full-width cut bounds."""
import argparse
import hashlib
from itertools import product
import json
from pathlib import Path
from freeze_tap_geometry import box,verify


def small_choices(domain,witness):
    choices=[]
    for p in sorted(witness,key=lambda p:p['id']):
        options=[]
        centres=((p['centre_x_um'],p['centre_y_um']),
                 (domain['interposer_side_um']-p['centre_y_um'],p['centre_x_um']))
        for (x,y),rotation in product(centres,(0,90,180,270)):
            candidate=dict(p,centre_x_um=x,centre_y_um=y,rotation_deg=rotation)
            try:box(domain,candidate)
            except ValueError:continue
            options.append(candidate)
        choices.append(options)
    return choices


def physical_geometry_key(domain,placements):
    # Only for this frozen uniform-core, symmetric-ring, isotropic thermal model.
    # A 180-degree rotation leaves its core and material fields unchanged.
    return tuple((p['id'],*box(domain,p),p['rotation_deg']%180) for p in placements)


def enumerate_small(domain,choices):
    legal=[];rejected=0;groups={}
    for ordinal,indices in enumerate(product(*(range(len(c)) for c in choices))):
        placement=[choices[i][j] for i,j in enumerate(indices)]
        try:verify(domain,placement)
        except ValueError:
            rejected+=1;continue
        legal.append(ordinal)
        key=physical_geometry_key(domain,placement)
        groups.setdefault(key,[]).append(list(indices))
    return dict(geometrically_legal_mixed_radix_ordinals=legal,overlap_or_gap_rejected=rejected,
        thermal_equivalence_classes=[dict(representative=items[0],member_count=len(items)) for items in groups.values()],
        geometry_feasible_count=len(legal),thermal_distinct_count=len(groups))


def full_width_cut_bound(domain,pitch_um=2):
    side=domain['interposer_side_um']
    if type(pitch_um) is not int or pitch_um<=0 or side%pitch_um:
        raise ValueError('Positive integer pitch dividing the interposer required')
    demands=domain['connection_wire_demands']
    if any(v<0 or int(v)!=v for row in demands for v in row):raise ValueError('Integer wire demand required')
    total=int(sum(sum(row) for row in demands))
    capacity=side//pitch_um
    return dict(total_directed_wire_demand=total,full_width_track_capacity=capacity,
        universal_crossing_demand_upper_bound=total,
        any_single_full_width_cut_can_reject=(total>capacity),
        scope='single straight full-width cut only, one signal layer normal to cut, all under-chip tracks available; no routability certificate')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--domains',type=Path,default=Path('docs/evidence/tap-geometry-domains.json'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();raw=args.domains.read_bytes();entries=json.loads(raw)['cases']
    entry=next(e for e in entries if e['domain']['name']=='ascend910');domain=entry['domain']
    choices=small_choices(domain,entry['witness']['placement'])
    counts=enumerate_small(domain,choices)
    result=dict(status='exact_geometry_domain_and_conditional_cut_bound_not_complete_routing_benchmark',
        domain_source_sha256=hashlib.sha256(raw).hexdigest(),case='ascend910',
        rule='independent Cartesian product: each published first-fit centre and its 90-degree package-centre image, with each of four independently chosen rotations; filter package boundary and 100um expanded-footprint gaps',
        choices=choices,**counts,
        rotation_reuse_scope='uniform centred power core, symmetric ring, isotropic layers; no inference about PHY or routing equivalence',
        full_width_cut_bounds={e['domain']['name']:full_width_cut_bound(e['domain']) for e in entries},
        unresolved=['physical PHY/bump signal map and clock/return allocation','metal layer count and via/escape rules','actual detailed routing witnesses or impossibility certificates','thermal candidate evaluation and mesh-sensitive ordering'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k in ('status','geometry_feasible_count','thermal_distinct_count','overlap_or_gap_rejected','full_width_cut_bounds')},indent=2))


if __name__=='__main__':main()
