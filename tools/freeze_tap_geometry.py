"""Freeze independent placement domains and check geometry-only witnesses."""
import argparse
from decimal import Decimal
from itertools import combinations
import json
from pathlib import Path

from audit_tap_capacity import source_capacities
from chiplet_floorplanning.characterization import digest


def micrometres(value):
    scaled = Decimal(str(value))*1000
    if not scaled.is_finite() or scaled <= 0 or scaled != scaled.to_integral_value():
        raise ValueError('positive dimensions on integer micrometres required')
    return int(scaled)


def freeze(case):
    if case['link_type'] != 'nppl' or case['upstream_placement_granularity_mm'] != 1:
        raise ValueError('only sourced nppl, 1 mm centre-grid cases supported')
    demands = case['connection_matrix_source_values']
    chips = []
    for i, (w, h) in enumerate(zip(case['widths_mm'], case['heights_mm'])):
        incident = sum(demands[i])+sum(row[i] for row in demands)
        ring, _ = source_capacities(w, h, incident)
        # The upstream ring has an integer number of 45 um rows.
        ring_um = 45*round(ring/.045)
        chips.append(dict(id=i, core_width_um=micrometres(w), core_height_um=micrometres(h),
                          bump_ring_um=ring_um, power_w=case['powers_w'][i]))
    return dict(name=case['name'], interposer_side_um=micrometres(case['interposer_side_mm']),
                centre_grid_um=1000, minimum_gap_um=100, rotations_deg=[0, 90, 180, 270],
                chiplets=chips, connection_wire_demands=demands,
                scope='expanded chiplet footprints; geometry only, not detailed routing or thermal qualification')


def box(domain, placement):
    """Twice-um bounds keep half-micrometre edges exact, without tolerances."""
    i = placement['id']
    if type(i) is not int or not 0 <= i < len(domain['chiplets']):
        raise ValueError('unknown chiplet')
    rotation = placement['rotation_deg']
    x, y = placement['centre_x_um'], placement['centre_y_um']
    if type(rotation) is not int or rotation not in domain['rotations_deg']:
        raise ValueError('rotation outside domain')
    if any(type(v) is not int or v % domain['centre_grid_um'] for v in (x, y)):
        raise ValueError('centre outside integer grid')
    chip = domain['chiplets'][i]
    w = chip['core_width_um']+2*chip['bump_ring_um']
    h = chip['core_height_um']+2*chip['bump_ring_um']
    if rotation in (90, 270):
        w, h = h, w
    bounds = (2*x-w, 2*y-h, 2*x+w, 2*y+h)
    if min(bounds[:2]) < 0 or max(bounds[2:]) > 2*domain['interposer_side_um']:
        raise ValueError('expanded footprint outside interposer')
    return bounds


def separated(a, b, gap_um):
    return max(a[0]-b[2], b[0]-a[2], a[1]-b[3], b[1]-a[3]) >= 2*gap_um


def verify(domain, placements):
    if sorted(p['id'] for p in placements) != list(range(len(domain['chiplets']))):
        raise ValueError('missing or duplicated chiplet')
    boxes = [box(domain, p) for p in placements]
    if any(not separated(a, b, domain['minimum_gap_um']) for a, b in combinations(boxes, 2)):
        raise ValueError('expanded footprint overlap or insufficient gap')
    return dict(status='geometry_feasible', checked_chiplets=len(boxes),
                checked_pairs=len(boxes)*(len(boxes)-1)//2, exact_integer_geometry=True)


def candidates(domain, chip):
    for rotation in domain['rotations_deg']:
        for y in range(0, domain['interposer_side_um']+1, domain['centre_grid_um']):
            for x in range(0, domain['interposer_side_um']+1, domain['centre_grid_um']):
                p = dict(id=chip['id'], centre_x_um=x, centre_y_um=y, rotation_deg=rotation)
                try:
                    bounds = box(domain, p)
                except ValueError:
                    continue
                yield p, bounds


def first_fit(domain):
    """Deterministic witness search only; failure never proves infeasibility."""
    order = sorted(domain['chiplets'], key=lambda c: (
        -(c['core_width_um']+2*c['bump_ring_um'])*(c['core_height_um']+2*c['bump_ring_um']), c['id']))
    placed, boxes = [], []
    for chip in order:
        for p, bounds in candidates(domain, chip):
            if all(separated(bounds, b, domain['minimum_gap_um']) for b in boxes):
                placed.append(p)
                boxes.append(bounds)
                break
        else:
            return dict(status='search_failed_unknown', partial_placement=placed)
    placed.sort(key=lambda p: p['id'])
    return dict(**verify(domain, placed), placement=placed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ledger = json.loads(args.ledger.read_text())
    domains = [freeze(c) for c in ledger['imported_cases']]
    result = dict(source_sha256=digest(__file__), ledger_sha256=digest(args.ledger),
                  upstream_commit=ledger['upstream_commit'], physical_qualified=False,
                  geometry_source='DATE 2021 Table I and III-C: 1 mm centre grid, 0.1 mm gap; pinned system.py initial_placement: bump-expanded footprint',
                  paper_url=ledger['paper_url'],
                  domain_rule='independent Cartesian product of each chiplet centre and four rotations, filtered by expanded-footprint boundaries and pair gaps; no shared translation or slot correlation',
                  outstanding=['physical track/escape model', 'package thermal transfer', 'bandwidth and full PHY qualification', 'small exact search reference and scalable extension'],
                  cases=[])
    for domain in domains:
        counts = [sum(1 for _ in candidates(domain, chip)) for chip in domain['chiplets']]
        result['cases'].append(dict(domain=domain, per_chiplet_candidate_counts=counts,
                                    witness=first_fit(domain)))
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({c['domain']['name']: c['witness']['status'] for c in result['cases']}))


if __name__ == '__main__':
    main()
