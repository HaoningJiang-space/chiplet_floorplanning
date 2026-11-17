"""MILP tractability of the K-direction distance (plan: docs/polygon-distance-plan.md, MILP section).

Per case, on its original carrier: the min-proxy MILP (proxy cap None) with the axial representation and with K
directions, Gurobi with cosize's settings; reports whether each gave a layout, its K-direction value and the time."""
import argparse
import json
from pathlib import Path
import time

from chiplet_floorplanning.placement import Problem
from chiplet_floorplanning.placement.lp import MILP_STATUS, milp_relations
from chiplet_floorplanning.placement.proxy import ThermalProxy


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cases', type=Path, nargs='+', required=True)
    p.add_argument('--directions', type=int, default=8)
    p.add_argument('--milp-s', type=float, default=60)
    p.add_argument('--warm', action='store_true', help='warm-start the K-direction MILP from the axial solution')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise SystemExit(f'{args.output} exists')
    rows = {}
    for path in args.cases:
        problem = Problem.from_imported(json.loads(path.read_text()))
        model = ThermalProxy.calibrate(problem, 0.0)
        row, axial = {}, None
        for name, k in (('axial', None), (f'polygon{args.directions}', args.directions)):
            started = time.perf_counter()
            # Revision (plan, MILP section): the K-direction solve is warm-started from the axial solution, which is
            # feasible for it; the axial time is part of its cost.
            layout = milp_relations(problem, 0.0, args.milp_s, proxy=(model, None), threads=8, focus=1, directions=k,
                                    start=axial if k and args.warm else None)
            if k is None:
                axial, axial_s = layout, time.perf_counter() - started
            seconds = time.perf_counter() - started + (axial_s if k and args.warm else 0.0)
            row[name] = dict(found=layout is not None, status=MILP_STATUS['status'], seconds=seconds,
                             value=None if layout is None else model.polygon_value(problem, layout, 0.0, args.directions))
        rows[path.stem] = row
        print(path.stem, {n: (r['found'], r['status'], round(r['seconds']), r['value'] and round(r['value'], 2))
                          for n, r in row.items()}, flush=True)
    poly = f'polygon{args.directions}'
    found_ok = sum(r[poly]['found'] for r in rows.values()) >= sum(r['axial']['found'] for r in rows.values())
    both = [r for r in rows.values() if r[poly]['found'] and r['axial']['found']]
    better = sum(r[poly]['value'] <= r['axial']['value'] + 1e-6 for r in both)
    verdict = 'adopt' if found_ok and both and better >= 0.7*len(both) else 'analyse'
    print(verdict, 'found', found_ok, 'not worse in', better, 'of', len(both))
    args.output.write_text(json.dumps(dict(check='polygon_milp', verdict=verdict, not_worse=better, both=len(both),
                                           cases=rows), indent=1, default=float) + '\n')


if __name__ == '__main__':
    main()
