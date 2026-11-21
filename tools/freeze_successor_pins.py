"""Separate coincident independent signal pads at fixed bus centres, without thermal scores."""
from collections import defaultdict
from hashlib import sha256

import numpy as np
from scipy.spatial.distance import pdist

from chiplet_floorplanning.placement import Problem, pin_manhattan_um
from evidence_io import write_json
from successor_protocol import EVIDENCE, ROOT, audit, load_case
from import_atplace_cases import parse_case


def main():
    name = 'Stagger12P'
    source = ROOT/'examples'/'Stagger12'
    dest = ROOT/'examples'/name
    dest.mkdir(exist_ok=True)
    raw = {ext:(source/f'Stagger12.{ext}').read_text(encoding='ascii') for ext in ('blocks','power','pl','nets')}
    lines = raw['nets'].splitlines()
    indices = [i for i,line in enumerate(lines) if ' B : ' in line]
    keys = [tuple(lines[i].split()) for i in indices]
    sides = defaultdict(list)
    for i,key in zip(indices,keys):
        die, _, _, px, py = key
        coords = [float(px[1:]),float(py[1:])]
        axis = int(abs(coords[0])>abs(coords[1]))  # tangent to the edge
        sides[die,axis,coords[1-axis]].append((coords[axis],i))
    for (die,axis,normal),pins in sides.items():
        if len(set(t for t,_ in pins))==len(pins):
            continue
        middle = np.mean([t for t,_ in pins])
        for rank,(_,i) in enumerate(sorted(pins)):
            coords = [normal,normal]
            coords[axis] = middle + rank - (len(pins)-1)/2
            lines[i] = f'{die} B : %{coords[0]:g} %{coords[1]:g}'
    raw['nets'] = '\n'.join(lines)+'\n'
    for ext,s in raw.items():
        (dest/f'{name}.{ext}').write_bytes(s.encode('ascii'))
    _,start,reach,_,_ = load_case('Stagger12',source)
    p = Problem.from_imported(parse_case(name,raw['blocks'],raw['power'],raw['nets']))
    distances = [pdist(p.pin_offset_um[p.pin_chip==i]).min() for i in range(p.count)]
    assert min(distances)>=50.
    cap = float(pin_manhattan_um(p,start).sum()/1e6)
    geom = audit(p,start,reach,cap)
    assert geom['admitted']
    rec = dict(name=name, files_sha256={ext:sha256(s.encode()).hexdigest() for ext,s in raw.items()},
               cap_m=cap, reach_mm=reach.tolist(),start_um=start.centre_um.tolist(),angles=start.rotation_deg.tolist(),
               original_unique=len(set(keys)),pin_occurrences=len(keys),min_separation_um=min(distances),
               source='Stagger12; crowded edges retain their pin centroid, with 1 percent tangent pitch in stable pin order')
    write_json(EVIDENCE/'successor-distinct-pins.json',rec)
    print(name,cap,min(distances),len(keys),geom['reach_violations'])


if __name__=='__main__':
    main()
