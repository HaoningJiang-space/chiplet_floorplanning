"""Explicit die-local landing coordinates to a finite interposer routing grid.

Coordinates are designed terminals, not measured/manufactured pad locations.
Routing below dies is allowed. Each bump column conservatively reserves every
other routing layer; power columns are unavailable on all signal layers.
"""

import math
from dataclasses import replace

from .model import ModelError, number
from .routing_graph import Fabric, Net, validate_inputs


def pin_fabric(case, specification):
    cfg = specification['fabric']
    fabric = Fabric(**cfg)
    clearance = number(specification['die_spacing_mm'], 'die_spacing_mm', minimum=0)
    boundary = number(specification['die_edge_clearance_mm'], 'die_edge_clearance_mm', minimum=0)
    for i, die in enumerate(case.dies):
        a = die.bounds
        if min(a.x, a.y, case.package.width-a.x-a.width, case.package.height-a.y-a.height) < boundary-1e-12:
            raise ModelError('die violates package edge clearance')
        for other in case.dies[:i]:
            b = other.bounds
            dx = max(a.x-b.x-b.width, b.x-a.x-a.width, 0.)
            dy = max(a.y-b.y-b.height, b.y-a.y-a.height, 0.)
            if math.hypot(dx, dy) < clearance-1e-12:
                raise ModelError('die spacing violation')
    margin = max(fabric.width_um, fabric.via_landing_um)/2+fabric.edge_clearance_um
    last = fabric.coordinates_mm((fabric.nx-1, fabric.ny-1, 0))
    if last[0]+margin/1000 > case.package.width+1e-12 or last[1]+margin/1000 > case.package.height+1e-12:
        raise ModelError('routing fabric and edge clearance exceed package')
    assignments = specification['pins']
    if set(assignments) != {die.id for die in case.dies}:
        raise ModelError('pin roles must cover every die')
    records = {}; blocked = set(fabric.blocked_nodes)
    for die in case.dies:
        if set(assignments[die.id]) != set(die.ports):
            raise ModelError('every physical pin needs exactly one role')
        for name, local in die.ports.items():
            info = assignments[die.id][name]
            if set(info) != {'kind', 'layer', 'diameter_um'} or info['kind'] not in ('data', 'clock', 'power'):
                raise ModelError('invalid pin contract')
            diameter = number(info['diameter_um'], 'pin diameter_um', positive=True)
            if diameter > fabric.via_landing_um:
                raise ModelError('pin landing exceeds declared fabric landing width')
            radius = diameter/2000
            if min(local[0], local[1], die.width-local[0], die.height-local[1]) < radius:
                raise ModelError('pin landing outside die')
            x, y = die.point(*local)
            for previous in records.values():
                px, py = previous['package_point_mm']; pd = previous['diameter_um']
                if math.hypot(x-px, y-py) < (diameter+pd)/2000+fabric.spacing_um/1000-1e-12:
                    raise ModelError('pin spacing violation')
            indices = [(v*1000-margin)/fabric.pitch_um for v in (x, y)]
            if any(abs(v-round(v)) > 1e-8 for v in indices):
                raise ModelError('pin is off the declared routing grid; no silent snapping')
            layer = info['layer']
            node = (*map(round, indices), layer)
            if not fabric.allowed(node):
                raise ModelError('pin terminal outside or blocked in fabric')
            key = (die.id, name)
            records[key] = dict(chiplet=die.id, port=name, kind=info['kind'], node=node,
                                local_point_mm=list(local), package_point_mm=[x, y], diameter_um=diameter)
            blocked.update((node[0], node[1], z) for z in range(fabric.layers)
                           if info['kind']=='power' or z != layer)
    used = set(); clocks = []; nets = []
    for link in case.links:
        ends = [records[(link[side]['chiplet'], link[side]['port'])] for side in ('source', 'target')]
        if any(p['kind'] != link['kind'] for p in ends):
            raise ModelError('signal net and pin roles disagree')
        used.update((p['chiplet'], p['port']) for p in ends)
        if link['kind']=='clock':
            clocks.append(ends)
        else:
            nets.append(Net(link['id'], 'data', ends[0]['node'], (ends[1]['node'],)))
    if not clocks or len({tuple(a['node']) for a, _ in clocks}) != 1:
        raise ModelError('one physical forwarded-clock source required')
    if used != {key for key, value in records.items() if value['kind'] != 'power'}:
        raise ModelError('unconnected physical signal pin')
    nets.append(Net('forwarded_clock', 'clock', clocks[0][0]['node'], tuple(b['node'] for _, b in clocks)))
    fabric = replace(fabric, blocked_nodes=frozenset(blocked))
    validate_inputs(fabric, nets)
    return fabric, tuple(nets), list(records.values())
