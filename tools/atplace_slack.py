"""Rigid-die separation DAGs with exact, normalized whitespace coordinates."""
from copy import deepcopy
from fractions import Fraction
from math import ceil, floor

from atplace_crossover import full_key
from atplace_pin_geometry import placement_geometry
from atplace_search import CostLimit


def encode(source, placement, gap_um, grid_um):
    """Encode any legal on-grid placement without compacting its whitespace."""
    placement_geometry(source, placement, gap_um)
    names = [c['name'] for c in source['chiplets']]
    if [p['chiplet'] for p in placement] != names:
        raise ValueError('Source and placement chiplet order differ')
    if any(type(p[k]) is not int or p[k] % grid_um for p in placement
           for k in ('centre_x_um', 'centre_y_um')):
        raise ValueError('Representation requires the frozen integer centre grid')
    dimensions = []
    for c, p in zip(source['chiplets'], placement):
        w, h = Fraction(c['width_um']), Fraction(c['height_um'])
        dimensions.append((h, w) if p['rotation_deg'] % 180 else (w, h))
    axes = []
    for axis, extent in enumerate(('interposer_width_um', 'interposer_height_um')):
        axes.append(dict(edges=[], lower=[ceil(d[axis]/(2*grid_um)) for d in dimensions],
            upper=[floor((Fraction(source[extent])-d[axis]/2)/grid_um) for d in dimensions],
            order=sorted(range(len(names)), key=lambda i: (placement[i][('centre_x_um', 'centre_y_um')[axis]], i))))
    coords = [[p[k]//grid_um for p in placement] for k in ('centre_x_um', 'centre_y_um')]
    # One witnessed separation per unordered pair. Prefer the greatest spare
    # separation; ties use x. Each axis graph follows strictly increasing centres.
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            options = []
            for axis in (0, 1):
                d = ceil(((dimensions[i][axis]+dimensions[j][axis])/2+Fraction(gap_um))/grid_um)
                delta = coords[axis][j]-coords[axis][i]
                if abs(delta) >= d:
                    options.append((abs(delta)-d, -axis, i if delta > 0 else j, j if delta > 0 else i, d))
            if not options:
                raise ValueError('Legal placement lacks a witnessed grid separation')
            _, negative_axis, u, v, distance = max(options)
            axes[-negative_axis]['edges'].append([u, v, distance])
    slacks = [[None, None] for _ in names]
    for axis, graph in enumerate(axes):
        outgoing = {i: [] for i in range(len(names))}
        incoming = {i: [] for i in range(len(names))}
        for u, v, distance in graph['edges']:
            outgoing[u].append((v, distance))
            incoming[v].append((u, distance))
        upper = graph['upper']
        for i in reversed(graph['order']):
            upper[i] = min([upper[i]]+[upper[j]-d for j, d in outgoing[i]])
        for i in graph['order']:
            lo = max([graph['lower'][i]]+[coords[axis][j]+d for j, d in incoming[i]])
            hi, value = upper[i], coords[axis][i]
            if not lo <= value <= hi:
                raise ValueError('Source pose outside its feasible slack interval')
            ratio = Fraction(value-lo, hi-lo) if hi > lo else Fraction(0)
            slacks[i][axis] = [ratio.numerator, ratio.denominator]
    return dict(names=names, rotations=[p['rotation_deg'] for p in placement],
                grid_um=grid_um, axes=axes, slacks=slacks)


def decode(topology, slacks):
    """Topological interval allocation; upper bounds reserve space for successors."""
    coords = []
    for axis, graph in enumerate(topology['axes']):
        incoming = {i: [] for i in range(len(topology['names']))}
        for u, v, distance in graph['edges']:
            incoming[v].append((u, distance))
        values = {}
        for i in graph['order']:
            lo = max([graph['lower'][i]]+[values[j]+d for j, d in incoming[i]])
            hi = graph['upper'][i]
            ratio = Fraction(*slacks[i][axis])
            if lo > hi or not 0 <= ratio <= 1:
                raise ValueError('Infeasible topology or slack outside [0,1]')
            # Deterministic nearest integer, halves upward, entirely rational.
            values[i] = lo+floor(ratio*(hi-lo)+Fraction(1, 2))
        coords.append(values)
    return [dict(chiplet=name, centre_x_um=coords[0][i]*topology['grid_um'],
                 centre_y_um=coords[1][i]*topology['grid_um'], rotation_deg=topology['rotations'][i])
            for i, name in enumerate(topology['names'])]


def slack_crossover(space, a, b, rng, receipt):
    """Inherit one feasible topology/rotation set, recombine per-die slack pairs."""
    receipt.update(selection='incomplete', geometry_checks=0, topology_pair_checks=0)
    def charge():
        if space.checks >= space.limit:
            raise CostLimit('candidate_check_cap')
        space.checks += 1
        receipt['geometry_checks'] += 1
    parents = []
    for p in (a, b):
        charge()
        parents.append(encode(space.source, p, space.gap, space.grid))
        receipt['topology_pair_checks'] += len(p)*(len(p)-1)//2
    topology_parent = rng.randrange(2)
    mask = rng.randrange(1, (1 << len(a))-1) if len(a) > 1 else 0
    slacks = [deepcopy(parents[bool(mask & (1 << i))]['slacks'][i]) for i in range(len(a))]
    charge()
    p = decode(parents[topology_parent], slacks)
    placement_geometry(space.source, p, space.gap)
    novel = full_key(p) not in (full_key(a), full_key(b))
    receipt.update(selection='novel_reconstruction' if novel else 'parent_reconstruction',
        topology_parent=topology_parent, slack_parent_mask=mask, encoded_parents=parents,
        offspring_slacks=slacks, placement=deepcopy(p),
        new_coordinate_genes=sum((z['centre_x_um'], z['centre_y_um']) not in
            ((x['centre_x_um'], x['centre_y_um']), (y['centre_x_um'], y['centre_y_um']))
            for x, y, z in zip(a, b, p)))
    return p
