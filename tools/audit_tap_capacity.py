"""Construct direct integer pin-flow witnesses for the scoped TAP abstraction."""
import argparse
import json
from pathlib import Path
from chiplet_floorplanning.characterization import digest


def direct_witness(capacities, demands):
    n = len(capacities)
    if len(demands) != n or any(len(row) != n for row in demands):
        raise ValueError('demand shape mismatch')
    if any(not row for row in capacities) or any(type(x) is not int or x < 0
            for row in [*capacities, *demands] for x in row):
        raise ValueError('nonnegative integer domain required')
    if any(demands[i][i] for i in range(n)):
        raise ValueError('self demands unsupported')
    loads = [sum(demands[i])+sum(row[i] for row in demands) for i in range(n)]
    violations = [dict(chiplet=i, required=loads[i], capacity=sum(capacities[i]))
                  for i in range(n) if loads[i] > sum(capacities[i])]
    if violations:
        return dict(status='infeasible_in_complete_direct_pin_model', cut_certificates=violations)
    residual = [row[:] for row in capacities]
    flows = []
    for i in range(n):
        for j in range(n):
            remaining = demands[i][j]
            while remaining:
                p = next(k for k, value in enumerate(residual[i]) if value)
                q = next(k for k, value in enumerate(residual[j]) if value)
                amount = min(remaining, residual[i][p], residual[j][q])
                residual[i][p] -= amount
                residual[j][q] -= amount
                remaining -= amount
                flows.append(dict(source=i, source_port=p, sink=j, sink_port=q, amount=amount))
    # Independently recompute conservation and port usage from the witness.
    delivered = [[0]*n for _ in range(n)]
    used = [[0]*len(row) for row in capacities]
    for f in flows:
        i, j, p, q, amount = (f[k] for k in ('source', 'sink', 'source_port', 'sink_port', 'amount'))
        delivered[i][j] += amount
        used[i][p] += amount
        used[j][q] += amount
    if delivered != demands or any(u > c for ur, cr in zip(used, capacities) for u, c in zip(ur, cr)):
        raise ValueError('witness verification failed')
    return dict(status='feasible_in_complete_direct_pin_model', incident_demands=loads,
                port_usage=used, flows=flows)


def source_capacities(width, height, incident):
    pitch = .045
    rows = 1
    stretch = pitch*rows
    while ((width+height)*2*stretch+4*stretch*stretch)/pitch/pitch < incident:
        rows += 1
        if rows > 1000:
            raise ValueError('upstream bump-ring limit exceeded')
        stretch = pitch*rows
    side = int(stretch/pitch)*int((height+stretch)/pitch)
    top = int(stretch/pitch)*int((width+stretch)/pitch)
    return stretch, [side, top, side, top]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ledger = json.loads(args.ledger.read_text())
    results = []
    for case in ledger['imported_cases']:
        if case['link_type'] != 'nppl':
            raise ValueError('this source audit is restricted to non-pipelined cases')
        raw = case['connection_matrix_source_values']
        if any(not float(x).is_integer() for row in raw for x in row):
            raise ValueError('noninteger source demands')
        demands = [[int(x) for x in row] for row in raw]
        capacities, rings = [], []
        for i, (width, height) in enumerate(zip(case['widths_mm'], case['heights_mm'])):
            incident = sum(demands[i])+sum(row[i] for row in demands)
            stretch, cap = source_capacities(width, height, incident)
            rings.append(stretch)
            capacities.append(cap)
        results.append(dict(name=case['name'], bump_ring_mm=rings, port_capacities=capacities,
                            **direct_witness(capacities, demands)))
    args.output.write_text(json.dumps(dict(source_sha256=digest(__file__),
        ledger_sha256=digest(args.ledger), upstream_commit=ledger['upstream_commit'],
        scope='complete direct pin-clump graph, no length limits or track capacity; not physical routing signoff',
        physical_qualified=False, cases=results), indent=2)+'\n')
    print(json.dumps([{k: r[k] for k in ('name', 'status', 'port_capacities')} for r in results]))


if __name__ == '__main__':
    main()
