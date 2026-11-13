"""Necessary capacity conditions on a declared two-layer interposer graph.

This is a rejection screen, not a router. Passing does not prove routability.
Pins retain their source coordinates; the bins only aggregate finite resources.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal

from atplace_pin_geometry import UniformDiePinEvaluator, pin_objective


DEFAULT_RESOURCES = dict(bin_um=1000, track_pitch_um=2,
                         horizontal_layers=1, vertical_layers=1,
                         access_pitch_um=2)


def screen_metric(metric, width_um, height_um, resources):
    """Count each independent two-pin net once across every tested cut.

    Test full-width/height cuts, each bin's perimeter cut, and the number of
    terminal accesses in each bin. Opposite directions share capacity. Cuts
    are against original resources, never a heuristic router's residual graph.
    """
    r = resources
    if set(r) != set(DEFAULT_RESOURCES) or any(type(v) is not int or v <= 0 for v in r.values()):
        raise ValueError('Positive integer routing dimensions and layer counts required')
    b, pitch, access_pitch = r['bin_um'], r['track_pitch_um'], r['access_pitch_um']
    if width_um % b or height_um % b or b % pitch or b % access_pitch:
        raise ValueError('Carrier and resource pitches must tile the routing bins')
    nx, ny = int(width_um//b), int(height_um//b)
    if min(nx, ny) < 1:
        raise ValueError('Empty routing carrier')
    hcap, vcap = b//pitch*r['horizontal_layers'], b//pitch*r['vertical_layers']
    acap = (b//access_pitch)**2
    xc, yc = [0]*(nx-1), [0]*(ny-1)
    escape, accesses = Counter(), Counter()
    seen = set()
    for net in metric['nets']:
        if net['net_id'] in seen or len(net['endpoints_um_decimal']) != 2:
            raise ValueError('Expected distinct independent two-pin nets')
        seen.add(net['net_id'])
        bins = []
        for point in net['endpoints_um_decimal']:
            x, y = map(Decimal, point)
            if not x.is_finite() or not y.is_finite() or not (0 <= x <= width_um and 0 <= y <= height_um):
                raise ValueError('Pin outside declared routing carrier')
            # Half-open bins; the outer maximum belongs to the last bin.
            cell = min(int(x//b), nx-1), min(int(y//b), ny-1)
            bins.append(cell)
            accesses[cell] += 1
        (ax, ay), (bx, by) = bins
        for i in range(min(ax, bx), max(ax, bx)):
            xc[i] += 1
        for j in range(min(ay, by), max(ay, by)):
            yc[j] += 1
        if bins[0] != bins[1]:
            escape.update(bins)

    cuts = []
    def add(kind, location, demand, capacity):
        cuts.append(dict(kind=kind, location=location, demand=demand, capacity=capacity,
                         utilization=demand/capacity if capacity else (0 if not demand else None),
                         passed=demand <= capacity))
    for i, demand in enumerate(xc):
        add('vertical_cut', [b*(i+1)], demand, ny*hcap)
    for j, demand in enumerate(yc):
        add('horizontal_cut', [b*(j+1)], demand, nx*vcap)
    for y in range(ny):
        for x in range(nx):
            cap = ((x > 0)+(x+1 < nx))*hcap + ((y > 0)+(y+1 < ny))*vcap
            add('bin_escape', [x, y], escape[x, y], cap)
            add('terminal_access', [x, y], accesses[x, y], acap)
    failed = [c for c in cuts if not c['passed']]
    worst = {}
    for kind in ('vertical_cut', 'horizontal_cut', 'bin_escape', 'terminal_access'):
        group = [c for c in cuts if c['kind'] == kind]
        worst[kind] = max(group, key=lambda c: float('inf') if c['utilization'] is None else c['utilization']) if group else None
    return dict(status='necessary_conditions_passed' if not failed else 'capacity_necessary_condition_failed',
                admitted=not failed, net_count=len(seen), terminal_count=sum(accesses.values()),
                checked_conditions=len(cuts), failed_conditions=failed, worst_by_kind=worst,
                resources=deepcopy(resources), carrier_um=[width_um, height_um],
                detailed_routing_proven=False,
                scope='necessary cuts/access bounds in an ideal aggregate graph; no paths, detailed escape, RC or timing')


def screen_placement(source, placement, gap_um, resources):
    metric = pin_objective(source, placement, gap_um)
    return screen_metric(metric, source['interposer_width_um'], source['interposer_height_um'], resources)


class RoutingScreenedEvaluator(UniformDiePinEvaluator):
    """Reject capacity violations before any thermal solve OR thermal cache access."""
    def __init__(self, source, gap_um, solver, resources=None, resolution=64):
        super().__init__(source, gap_um, solver, resolution)
        self.resources = deepcopy(DEFAULT_RESOURCES if resources is None else resources)
        self.routing_checks = self.routing_rejections = 0

    def evaluate(self, placement):
        routing = screen_placement(self.case, placement, self.gap_um, self.resources)
        self.routing_checks += 1
        if not routing['admitted']:
            self.routing_rejections += 1
            return dict(status='rejected_routing_necessary_condition', routing=routing)
        result = super().evaluate(placement)
        result.update(status='evaluated_after_necessary_screen', routing=routing)
        return result
