"""Read numeric TTC geometry facts from pinned public author files.

This parser does not execute or reproduce the upstream GPL comparison scripts.
Material values labeled fitted are not independent measured constraints.
"""

import hashlib
import json
from pathlib import Path
import re
import tarfile
from urllib.request import urlopen

import numpy as np

LOCK = Path(__file__).resolve().parents[1] / 'ttc-upstream.lock.json'


def verify(root):
    lock = json.loads(LOCK.read_text())
    for r in lock['files']:
        if hashlib.sha256((root/r['path']).read_bytes()).hexdigest() != r['sha256']:
            raise ValueError('upstream source hash mismatch: ' + r['path'])
    return lock


def bootstrap(root):
    """Download pinned files and only locked, regular archive members."""
    root = Path(root).resolve()
    lock = json.loads(LOCK.read_text())
    for r in lock['files']:
        path = root / r['path']
        if not path.resolve().is_relative_to(root):
            raise ValueError('unsafe source path')
        if path.exists():
            data = path.read_bytes()
        elif 'url' in r:
            with urlopen(r['url'], timeout=120) as stream:
                data = stream.read()
        else:
            with tarfile.open(root/r['archive']) as archive:
                member = archive.getmember(r['member'])
                if not member.isfile():
                    raise ValueError('expected regular archive member')
                data = archive.extractfile(member).read()
        if hashlib.sha256(data).hexdigest() != r['sha256']:
            raise ValueError('upstream source hash mismatch: ' + r['path'])
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
    return verify(root)


def number(text, name):
    match = re.search(r'\b' + re.escape(name) + r'\s*=\s*([\d.eE+-]+)', text)
    if not match:
        raise ValueError('missing numeric source fact: ' + name)
    return float(match[1])


def check_geometry(heaters, sensors, die_um):
    """Check both conservation and sensor/input association (not just totals)."""
    weights = np.zeros(16)
    for h in heaters:
        x, y, dx, dy = (h[k] for k in ('x_um', 'y_um', 'width_um', 'height_um'))
        if min(x, y) < 0 or min(dx, dy) <= 0 or max(x+dx, y+dy) > die_um:
            raise ValueError('heater outside die')
        weights[h['power_index']] += h['power_fraction']
    if not np.allclose(weights, 1., rtol=0, atol=1e-12):
        raise ValueError('heater power allocation is not conservative')
    for index, sensor in enumerate(sensors):
        pair = [h for h in heaters if h['power_index'] == index]
        if len(pair) != 2:
            raise ValueError('expected two heaters for each sensor')
        center = [np.mean([h['x_um']+h['width_um']/2 for h in pair]),
                  np.mean([h['y_um']+h['height_um']/2 for h in pair])]
        if not np.allclose(center, sensor, rtol=0, atol=1e-9):
            raise ValueError('sensor/input geometry association mismatch')
        for h in pair:
            if (h['x_um'] <= sensor[0] <= h['x_um']+h['width_um']
                    and h['y_um'] <= sensor[1] <= h['y_um']+h['height_um']):
                raise ValueError('sensor unexpectedly inside heater')
    for i, a in enumerate(heaters):
        for b in heaters[i+1:]:
            overlap = [min(a[k]+a[d], b[k]+b[d])-max(a[k], b[k])
                       for k, d in [('x_um', 'width_um'), ('y_um', 'height_um')]]
            if min(overlap) > 0:
                raise ValueError('overlapping heaters')
    return dict(heater_count=len(heaters), power_fraction_per_channel=weights.tolist(),
                total_heater_area_um2=sum(h['width_um']*h['height_um'] for h in heaters),
                geometry_conservation_screen=True)


def extract(root):
    lock = verify(root)
    source = root/'ice3-validation'
    gen = (source/'gencell.cpp').read_text()
    stk = (source/'TTC-nofan-batch.stk').read_text()
    fan = (source/'TTC-fan-batch.stk').read_text()
    sink = (root/'ice3/heatsink_plugin/heatsinks/HS483/HS483.mo').read_text()
    mapping_block = re.search(r'mapping\[4\]\[4\]\s*=\s*\{(.*?)\};', gen, re.S)[1]
    mapping = np.array([int(v) for v in re.findall(r'\d+', mapping_block)]).reshape(4, 4)
    cx, cy, hx, hy, ox, oy = [number(gen, s) for s in
                             ('cellX', 'cellY', 'heaterX', 'heaterY', 'heaterOffsetX', 'heaterOffsetY')]
    if cx != cy:
        raise ValueError('unexpected nonsquare source cell')
    sensors = [[float(x), float(y)] for x, y in re.findall(r'T\s*\(\s*D1,\s*(\d+),\s*(\d+)', stk)]
    heaters = []
    for r in range(4):
        for col in range(4):
            for y in ((3-r)*cy+oy, (4-r)*cy-oy-hy):
                heaters.append(dict(power_index=int(mapping[r, col]), power_fraction=.5,
                                    x_um=col*cx+ox, y_um=y, width_um=hx, height_um=hy))
    check = check_geometry(heaters, sensors, 4*cx)
    materials = {}
    for key, text in [('natural', stk), ('fan', fan)]:
        material = {}
        for name, k, cv in re.findall(r'material\s+(\w+)\s*:\s*thermal conductivity\s+([\deE.-]+)\s*;\s*volumetric heat capacity\s+([\deE.-]+)', text):
            material[name] = dict(conductivity_w_per_m_k=float(k)*1e6,
                                  volumetric_capacity_j_per_m3_k=float(cv)*1e18)
        materials[key] = material
    bulk_um = float(re.search(r'layer\s+(\d+)\s+SILICON', stk)[1])
    active_um = float(re.search(r'source\s+(\d+)\s+SILICON', stk)[1])
    pad_um = float(re.search(r'spreader length\s+\d+\s*,\s*width\s+\d+\s*,\s*height\s+(\d+)', stk)[1])
    area_m2 = (4*cx*1e-6)**2
    cv_si = materials['natural']['SILICON']['volumetric_capacity_j_per_m3_k']
    cv_pad = materials['natural']['SILICONE']['volumetric_capacity_j_per_m3_k']
    cp, rho, length, width, height, finh, fint, fins = [number(sink, s) for s in
        ('cp', 'rho', 'baseLength', 'baseWidth', 'baseHeight', 'finHeight', 'finThickness', 'baseCols')]
    capacities = dict(silicon_total_j_per_k=area_m2*(bulk_um+active_um)*1e-6*cv_si,
                      silicon_active_j_per_k=area_m2*active_um*1e-6*cv_si,
                      modeled_pad_j_per_k=area_m2*pad_um*1e-6*cv_pad,
                      copper_base_j_per_k=length*width*height*cp*rho,
                      copper_fins_j_per_k=fins*finh*fint*width*cp*rho)
    capacities['copper_total_j_per_k'] = capacities['copper_base_j_per_k']+capacities['copper_fins_j_per_k']
    capacities['silicon_per_cell_j_per_k'] = capacities['silicon_total_j_per_k']/16
    return dict(source_commit=lock['commit'], source_lock_sha256=hashlib.sha256(LOCK.read_bytes()).hexdigest(),
                die_side_um=4*cx, paper_rounded_die_side_mm=10.23,
                sensors_xy_um=sensors, heaters=heaters, checks=check,
                bulk_silicon_um=bulk_um, active_silicon_um=active_um, thermal_pad_um=pad_um,
                heater_gap_um=cy-2*(oy+hy), materials=materials, capacities=capacities,
                provenance=dict(geometry='author validation code; paper dimensions rounded differently',
                                silicon_conductivity='fitted by author',
                                pad_conductivity_and_capacity='fitted by author, includes contact effects',
                                copper='author model geometry and material properties',
                                capacities='derived from author model, not new calorimetry'),
                observation_contract=dict(author_evaluation='interval_end', hardware_timestamp_verified=False,
                                          author_errors='selected residual spikes replaced by neighboring averages; MAE and max',
                                          our_errors='raw, unsmoothed MAE/RMSE/max on all 26 runs',
                                          author_excluded_patterns=['sixteen'], model_power_limit_w=40),
                physical_model_qualified=False)
