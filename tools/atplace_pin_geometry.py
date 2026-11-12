"""ATPlace source pins and a declared common FV package, without routed RC/timing."""
from decimal import Decimal
from copy import deepcopy

from chiplet_floorplanning.model import parse_case
from import_atplace_cases import rotate_offset


def placement_geometry(case, placements, gap_um):
    """Centres and CCW orientations; exact source units, no silent snapping."""
    chips = {c['name']: c for c in case['chiplets']}
    poses = {p['chiplet']: p for p in placements}
    if len(poses) != len(placements) or poses.keys() != chips.keys():
        raise ValueError('placement must contain each source chiplet exactly once')
    gap = Decimal(str(gap_um))
    if not gap.is_finite() or gap < 0:
        raise ValueError('invalid minimum gap')
    boxes = {}
    for name, p in poses.items():
        if type(p['rotation_deg']) is not int or p['rotation_deg'] not in (0, 90, 180, 270):
            raise ValueError('only quarter turns supported')
        x, y = (Decimal(str(p[k])) for k in ('centre_x_um', 'centre_y_um'))
        if not x.is_finite() or not y.is_finite():
            raise ValueError('nonfinite centre')
        w, h = (Decimal(chips[name][k]) for k in ('width_um', 'height_um'))
        if p['rotation_deg'] % 180:
            w, h = h, w
        box = x-w/2, y-h/2, x+w/2, y+h/2
        if box[0] < 0 or box[1] < 0 or box[2] > case['interposer_width_um'] or box[3] > case['interposer_height_um']:
            raise ValueError('chiplet outside source interposer')
        for other in boxes.values():
            if not (box[2]+gap <= other[0] or other[2]+gap <= box[0]
                    or box[3]+gap <= other[1] or other[3]+gap <= box[1]):
                raise ValueError('chiplets overlap or violate declared gap')
        boxes[name] = box
    return poses, boxes


def pin_objective(case, placements, gap_um):
    """Sum the two-pin Manhattan lower bound, preserving every source net."""
    poses, _ = placement_geometry(case, placements, gap_um)
    pin_total, centre_total = Decimal(0), Decimal(0)
    rows = []
    for net in case['nets']:
        points, centres = [], []
        for pin in net['pins']:
            p = poses[pin['chiplet']]
            x, y = (Decimal(str(p[k])) for k in ('centre_x_um', 'centre_y_um'))
            dx, dy = map(Decimal, rotate_offset(pin['offset_x_um_decimal'],
                                               pin['offset_y_um_decimal'], p['rotation_deg']))
            points.append((x+dx, y+dy))
            centres.append((x, y))
        length = sum(abs(a-b) for a, b in zip(*points))
        pin_total += length
        centre_total += sum(abs(a-b) for a, b in zip(*centres))
        rows.append(dict(net_id=net['id'], endpoints_um_decimal=[[str(x), str(y)] for x, y in points],
                         pin_manhattan_um_decimal=str(length)))
    return dict(total_pin_manhattan_um_decimal=str(pin_total),
                total_pin_manhattan_mm=float(pin_total/1000),
                total_pin_manhattan_m=float(pin_total/1000000),
                total_centre_manhattan_mm=float(centre_total/1000),
                net_count=len(rows), nets=rows,
                scope='total two-pin Manhattan lower bound; no obstacle detours, capacity, RC or timing')


def make_thermal_case(case, placements, gap_um, resolution=64):
    """Use the existing TAP-family material recipe with the source carrier size.

    Fixed 100 mm spreader / 200 mm sink and fixed h; this is an explicit research
    adaptation, not ATPlace's native thermal model or a measured package.
    Source blocks are full uniformly powered dies; no invented external bump ring.
    """
    poses, boxes = placement_geometry(case, placements, gap_um)
    width, height = case['interposer_width_um']/1000, case['interposer_height_um']/1000
    if max(width, height) > 100:
        raise ValueError('source carrier exceeds this declared common spreader')
    ox, oy = (200-width)/2, (200-height)/2
    provenance = ('ATPlace source geometry/power/pins; declared TAP-family FV materials, '
                  'fixed 100/200 mm spreader/sink; not native ATPlace or measured calibration')
    chips = []
    for c in case['chiplets']:
        name = c['name']
        w, h = c['width_um']/1000, c['height_um']/1000
        ports = {}
        for net in case['nets']:
            for i, pin in enumerate(net['pins']):
                if pin['chiplet'] == name:
                    ports[f"n{net['id']}_{i}"] = dict(
                        x=w/2+float(Decimal(pin['offset_x_um_decimal'])/1000),
                        y=h/2+float(Decimal(pin['offset_y_um_decimal'])/1000))
        chips.append(dict(id=name, size_mm=dict(width=w, height=h),
                          placement_mm=dict(x=ox+float(boxes[name][0]/1000), y=oy+float(boxes[name][1]/1000)),
                          rotation_deg=poses[name]['rotation_deg'], ports_mm=ports,
                          blocks=[dict(id='core', rect_mm=dict(x=0, y=0, width=w, height=h),
                                       power_w=float(c['power_w_decimal']), provenance=provenance)]))

    def layer(name, thickness, conductivity, w=width, h=height, die_k=None):
        item = dict(id=name, thickness_mm=thickness, conductivity_w_mk=conductivity,
                    footprint='rectangle', rect_mm=dict(x=(200-w)/2, y=(200-h)/2, width=w, height=h))
        if die_k is not None:
            item['die_materials'] = {c['id']: dict(conductivity_w_mk=die_k) for c in chips}
        return item

    def mixture(diameter, pitch, background):
        return 400*(diameter/pitch)**2+background*(1-(diameter/pitch)**2)

    layers = [layer('substrate', .2, 1/3.33), layer('c4', .07, mixture(250, 600, 1.6)),
              layer('interposer', .11, mixture(10, 50, 100)),
              layer('microbumps', .01, 1.6, die_k=mixture(25, 45, 1.6)),
              layer('dies', .15, 1.6, die_k=100), layer('tim', .02, 4),
              layer('spreader', 1, 400, 100, 100), layer('sink', 6.9, 400, 200, 200)]
    data = dict(schema_version=1, name='atplace_fv_'+case['name'],
                package_mm=dict(width=200, height=200),
                grid=dict(nx=resolution, ny=resolution, mode='geometry_conformal'), chiplets=chips,
                thermal=dict(model='layered_package_steady', ambient_c=45, top_h_w_m2k=1/(.1*.06**2),
                             bottom_h_w_m2k=0, power_layer='dies', provenance=provenance, layers=layers),
                interconnect=dict(model='manhattan_lower_bound', r_ohm_per_mm=0, c_pf_per_mm=0,
                                  provenance='Unused electrical placeholders; source B pins are evaluated as undirected nets separately'),
                links=[])
    parse_case(data)
    return data


class UniformDiePinEvaluator:
    """Private thermal cache for this fixed, uniformly powered/materialed case.

    Physical bounds determine the thermal problem for this particular adapter.
    Full orientations determine source-pin positions. Never cache both objectives
    under the thermal key, or use that key to suppress distinct search layouts.
    A nonuniform die model would require a different thermal equivalence rule.
    """
    def __init__(self, case, gap_um, solver, resolution=64):
        self.case = deepcopy(case)
        self.gap_um, self.solver, self.resolution = gap_um, solver, resolution
        self.thermal_cache = {}
        self.solve_count = self.cache_hits = 0

    def evaluate(self, placements):
        poses, boxes = placement_geometry(self.case, placements, self.gap_um)
        layout_key = tuple((name, Decimal(str(p['centre_x_um'])), Decimal(str(p['centre_y_um'])),
                            p['rotation_deg']) for name, p in sorted(poses.items()))
        thermal_key = tuple((name, *bounds) for name, bounds in sorted(boxes.items()))
        metric = pin_objective(self.case, placements, self.gap_um)
        data = make_thermal_case(self.case, placements, self.gap_um, self.resolution)
        hit = thermal_key in self.thermal_cache
        if hit:
            self.cache_hits += 1
        else:
            self.thermal_cache[thermal_key] = self.solver(data)
            self.solve_count += 1
        return dict(layout_key=layout_key, metric=metric, case_data=data,
                    thermal_result=self.thermal_cache[thermal_key], thermal_cache_hit=hit)
