"""Exact incident-net updates for the frozen uniform-die orientation scan.

The mathematical decisions match the full-objective reference. This changes
evaluation cost, not the physical model, tie rule, or orientation neighborhood.
"""
from copy import deepcopy
from decimal import Decimal
import time

from atplace_pin_geometry import pin_objective, placement_geometry
from atplace_routing_screen import screen_metric
from atplace_search import identities
from import_atplace_cases import rotate_offset


class IncidentPinRepair:
    def __init__(self, source, gap_um):
        started = time.perf_counter()
        self.source, self.gap_um = deepcopy(source), gap_um
        self.incident = {c['name']: [] for c in source['chiplets']}
        self.nets = []
        for i, net in enumerate(source['nets']):
            if len(net['pins']) != 2:
                raise ValueError('Expected two-pin source nets')
            pins = []
            for pin in net['pins']:
                offsets = {angle: tuple(map(Decimal, rotate_offset(pin['offset_x_um_decimal'],
                                                                 pin['offset_y_um_decimal'], angle)))
                           for angle in (0, 90, 180, 270)}
                pins.append((pin['chiplet'], offsets))
            self.nets.append(pins)
            # A same-die two-pin net is updated once, with both endpoints rotated.
            for name in {p[0] for p in pins}:
                self.incident[name].append(i)
        self.setup_seconds = time.perf_counter()-started

    def repair(self, placement):
        started = time.perf_counter()
        current = deepcopy(placement)
        poses, bounds = placement_geometry(self.source, current, self.gap_um)
        centres = {name: (Decimal(str(p['centre_x_um'])), Decimal(str(p['centre_y_um'])))
                   for name, p in poses.items()}

        def endpoints(index, changed=None, angle=None):
            return [(centres[name][0]+offsets[angle if name == changed else poses[name]['rotation_deg']][0],
                     centres[name][1]+offsets[angle if name == changed else poses[name]['rotation_deg']][1])
                    for name, offsets in self.nets[index]]

        def length(points):
            return abs(points[0][0]-points[1][0])+abs(points[0][1]-points[1][1])

        lengths = [length(endpoints(i)) for i in range(len(self.nets))]
        total = initial = sum(lengths, Decimal(0))
        net_updates, trials = len(self.nets), []
        for chip in self.source['chiplets']:
            name = chip['name']
            incumbent = poses[name]['rotation_deg']
            angles = (0, 90, 180, 270) if chip['width_um'] == chip['height_um'] else sorted((incumbent, (incumbent+180) % 360))
            indices = self.incident[name]
            old_sum = sum((lengths[i] for i in indices), Decimal(0))
            best_total, best_angle, best_lengths = total, incumbent, None
            for angle in angles:
                if angle == incumbent:
                    continue
                changed = [length(endpoints(i, name, angle)) for i in indices]
                candidate_total = total-old_sum+sum(changed, Decimal(0))
                net_updates += len(indices)
                trials.append(dict(chiplet=name, rotation_deg=angle, pin_length_um_decimal=str(candidate_total)))
                if candidate_total < best_total:
                    best_total, best_angle, best_lengths = candidate_total, angle, changed
            if best_lengths is not None:
                for i, value in zip(indices, best_lengths):
                    lengths[i] = value
            poses[name]['rotation_deg'], total = best_angle, best_total
            trials[-1]['selected_rotation_deg_after_chip'] = best_angle
        # One full recomputation supplies actual endpoints to the routing gate.
        metric = pin_objective(self.source, current, self.gap_um)
        net_updates += len(self.nets)
        if (Decimal(metric['total_pin_manhattan_um_decimal']) != total
                or placement_geometry(self.source, current, self.gap_um)[1] != bounds):
            raise ValueError('Incident repair changed bounds or disagreed with full pins')
        return dict(placement=current, metric=metric, before_pin_length_m=float(initial/1000000),
                    trials=trials, effort=dict(full_pin_recomputations=1, net_length_evaluations=net_updates,
                                              orientation_trials=len(trials)),
                    elapsed_seconds=time.perf_counter()-started)

    def prepare(self, placement, resources):
        started = time.perf_counter()
        result = self.repair(placement)
        full, thermal = identities(self.source, result['placement'], self.gap_um)
        routing = screen_metric(result['metric'], self.source['interposer_width_um'],
                                self.source['interposer_height_um'], resources)
        return dict(placement=result['placement'], layout_key=[list(x) for x in full],
                    thermal_key=[list(x) for x in thermal], routing=routing,
                    pin_length_m=result['metric']['total_pin_manhattan_m'],
                    pin_length_um_decimal=result['metric']['total_pin_manhattan_um_decimal'],
                    before_pin_length_m=result['before_pin_length_m'], trials=result['trials'],
                    effort=result['effort'], preparation_seconds=time.perf_counter()-started)
