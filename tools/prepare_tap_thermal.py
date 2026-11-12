"""Generate pinned TAP thermal inputs without invoking its search or simulator."""
import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

from freeze_tap_geometry import box, candidates, separated, verify
from import_tap_source_ledger import COMMIT


def thermal_margin(domain, placement):
    bounds = box(domain, placement)
    # TAP reserves half the placement grid on each side in its thermal FLPs.
    margin_twice_um = domain['centre_grid_um']
    return min(bounds[:2]) >= margin_twice_um and max(bounds[2:]) <= 2*domain['interposer_side_um']-margin_twice_um


def thermal_witness(domain):
    placed, boxes = [], []
    order = sorted(domain['chiplets'], key=lambda c: (
        -(c['core_width_um']+2*c['bump_ring_um'])*(c['core_height_um']+2*c['bump_ring_um']), c['id']))
    for chip in order:
        for p, bounds in candidates(domain, chip):
            if thermal_margin(domain, p) and all(separated(bounds, b, domain['minimum_gap_um']) for b in boxes):
                placed.append(p)
                boxes.append(bounds)
                break
        else:
            raise ValueError('Thermal-compatible witness search failed; feasibility unknown')
    placed.sort(key=lambda p: p['id'])
    verify(domain, placed)
    return placed


def check_partition(path, side_m):
    blocks = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        fields = line.split()
        w, h, x, y = map(float, fields[1:5])
        if not all(math.isfinite(v) for v in (w,h,x,y)) or min(w,h) <= 0:
            raise ValueError('Invalid thermal rectangle')
        if min(x,y) < -1e-12 or max(x+w,y+h) > side_m+1e-12:
            raise ValueError('Thermal rectangle outside package')
        blocks.append((fields[0],w,h,x,y))
    if len({b[0] for b in blocks}) != len(blocks):
        raise ValueError('Duplicate thermal block')
    for i, (_, w,h,x,y) in enumerate(blocks):
        for _,v,z,a,b in blocks[:i]:
            if min(x+w,a+v)-max(x,a) > 1e-12 and min(y+h,b+z)-max(y,b) > 1e-12:
                raise ValueError('Overlapping thermal rectangles')
    area = math.fsum(w*h for _,w,h,_,_ in blocks)
    if abs(area-side_m**2) > 1e-12:
        raise ValueError('Incomplete thermal partition')
    return dict(blocks=len(blocks), area_m2=area, package_area_m2=side_m**2)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tap',type=Path,required=True)
    p.add_argument('--domains',type=Path,default=Path('docs/evidence/tap-geometry-domains.json'))
    p.add_argument('--case',choices=['ascend910','micro150','multigpu'],required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    entry=next(c for c in json.loads(args.domains.read_text())['cases'] if c['domain']['name']==args.case)
    domain=entry['domain']
    placements=thermal_witness(domain)
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    sources={name:subprocess.check_output(['git','show',f'{COMMIT}:{name}'],cwd=args.tap) for name in ('passive_interposer.py','util/fill_space.py','util/hotspot.config')}
    # Execute only the original two generator method bodies, unchanged, and
    # their original fill-space helper. Never import upstream optimizer code.
    module=ast.parse(sources['passive_interposer.py'])
    cls=next(n for n in module.body if isinstance(n,ast.ClassDef) and n.name=='PassiveInterposer')
    methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('gen_flp','gen_ptrace')]
    helper={'__name__':'tap_fill_space'}
    exec(compile(sources['util/fill_space.py'],'pinned_tap_fill_space','exec'),helper)
    namespace={'os':os,'util':SimpleNamespace(fill_space=SimpleNamespace(**helper))}
    exec(compile(ast.Module(body=methods,type_ignores=[]),'pinned_tap_generators','exec'),namespace)
    model=SimpleNamespace(chiplet_count=len(placements),intp_size=domain['interposer_side_um']/1000,
        granularity=domain['centre_grid_um']/1000,path=out.as_posix()+'/',width=[],height=[],hubump=[],power=[],x=[],y=[])
    for c,placement in zip(domain['chiplets'],placements):
        w,h=c['core_width_um']/1000,c['core_height_um']/1000
        if placement['rotation_deg'] in (90,270): w,h=h,w
        model.width.append(w); model.height.append(h)
        model.hubump.append(c['bump_ring_um']/1000); model.power.append(c['power_w'])
        model.x.append(placement['centre_x_um']/1000); model.y.append(placement['centre_y_um']/1000)
    (out/'util').mkdir()
    (out/'util/hotspot.config').write_bytes(sources['util/hotspot.config'])
    previous=Path.cwd()
    try:
        os.chdir(out)
        namespace['gen_flp'](model,'case')
        namespace['gen_ptrace'](model,'case')
    finally:
        os.chdir(previous)
    partitions={f.name:check_partition(f,model.intp_size/1000) for f in out.glob('caseL*_*.flp')}
    ptrace=(out/'case.ptrace').read_text().splitlines()
    values=dict(zip(ptrace[0].split(),map(float,ptrace[1].split()),strict=True))
    expected={f'Chiplet_{i}':v for i,v in enumerate(model.power)}
    if any(values.get(k)!=v for k,v in expected.items()) or any(v!=0 for k,v in values.items() if k not in expected):
        raise ValueError('Thermal power mapping differs from source')
    result=dict(case=args.case,upstream_commit=COMMIT,placement=placements,
        original_witness_thermal_margin_violations=[p['id'] for p in entry['witness']['placement'] if not thermal_margin(domain,p)],
        scope='source thermal-input compatibility, not a physical keepout or routing feasibility certificate',
        total_power_w=sum(values.values()),partitions=partitions,
        source_hashes={k:hashlib.sha256(v).hexdigest() for k,v in sources.items()},
        generated_hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in out.iterdir() if f.is_file()})
    (out/'inputs.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
