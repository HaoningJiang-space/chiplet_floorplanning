"""Two of our own methods' fronts on the same cases, FV model (plan: docs/thermal-milp-plan.md).

Each front gives 16 layouts evenly by length; margin dominance and the per-case outcome follow the ATPlace
comparison (atplace_compare.outcome), with the new method in the role of "ours".
"""
import argparse
import json
from pathlib import Path

import numpy as np

from atplace_compare import outcome, pick
import frozen_front


def front_points(case, run):
    front = frozen_front.load(case, run/'summary.json', run/'layouts.npz')
    keep = pick(front.length_m)
    return [(float(front.length_m[i]), float(front.peak_c[i])) for i in keep], front.summary


def verdict(rows):
    wins = sum(r['outcome'] == 'ours' for r in rows.values())
    losses = sum(r['outcome'] == 'atplace' for r in rows.values())
    return ('improved' if wins >= 4 and losses <= 1 else 'worse' if losses >= 3 else 'no_clear_difference'), wins, losses


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cases', type=int, nargs='+', default=list(range(1, 11)))
    p.add_argument('--import-dir', type=Path, default=Path('results/physical-calibration/atplace-import-v1'))
    p.add_argument('--new', type=Path, required=True)
    p.add_argument('--old', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    rows = {}
    for n in args.cases:
        case = args.import_dir/f'Case{n}.json'
        new, summary = front_points(case, args.new/f'case{n}')
        old, old_summary = front_points(case, args.old/f'case{n}')
        row = outcome(new, old)
        row.update(new_wall_s=summary['wall_seconds'], old_wall_s=old_summary['wall_seconds'],
                   new_shortest_m=min(l for l, _ in new), old_shortest_m=min(l for l, _ in old),
                   new_coolest_c=min(t for _, t in new), old_coolest_c=min(t for _, t in old),
                   notes=summary.get('method_notes'))
        rows[f'Case{n}'] = row
        print(f'Case{n}', row['outcome'], 'D_new', round(row['d_ours'], 2), 'D_old', round(row['d_atp'], 2),
              'coolest', round(row['new_coolest_c'], 2), 'vs', round(row['old_coolest_c'], 2),
              'shortest', round(row['new_shortest_m'], 3), 'vs', round(row['old_shortest_m'], 3), flush=True)
    result, wins, losses = verdict(rows)
    args.output.write_text(json.dumps(dict(plan='docs/thermal-milp-plan.md', verdict=result, wins=wins, losses=losses,
                                           cases=rows), indent=1, default=float) + '\n')
    print(result, wins, losses)


if __name__ == '__main__':
    main()
