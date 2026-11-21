"""Compare five or three starting hotspot rows and cold-start ATPlace on frozen inputs."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from evidence_io import write_json


CASES = ('Case7', 'Case8', 'Stagger12P', 'DualStar14')


def run_arm(args):
    import numpy as np
    from chiplet_floorplanning.placement import continuous_hotspot_moves
    from successor_protocol import audit, load_case, measure, result

    t = perf_counter()
    p, start, reach, cap, encoded = load_case(args.case, args.source)
    admission = audit(p, start, reach, cap)
    if not admission['admitted']:
        raise ValueError('invalid common start')
    base = dict(measure(p, start, admission), origin='start')
    common_s = perf_counter() - t
    if args.arm == 'ATPlace':
        from successor_atplace import external_arm
        record = external_arm(p, start, reach, cap, base, encoded, args)
    else:
        t = perf_counter()
        meta, proposals = continuous_hotspot_moves(p, start, reach, cap, base['die_peaks_c'],
                                                   hotspot_count=int(args.arm))
        geometry_s = perf_counter() - t
        t = perf_counter()
        rows, rejected = [base], []
        for fraction, pose, forecast in proposals:
            row = audit(p, pose, reach, cap)
            move = (pose.centre_um-start.centre_um)/1000
            if abs(move).max() > meta['radius_mm']+1e-9:
                raise ValueError('proposal left the shared trust region')
            if not row['admitted']:
                rejected.append(dict(row, fraction=fraction))
                continue
            rows.append(dict(measure(p, pose, row), fraction=fraction, predicted_c=forecast,
                             moved_dies=int(np.any(move != 0, axis=1).sum())))
        record = dict(result(rows, base, len(rows)-1), **meta, reduced_labels=0,
                      geometry_s=geometry_s, admission_and_verify_s=perf_counter()-t, rejected=rejected)
    assert record['new_board_checks'] <= 2 and record['reduced_labels'] <= 5
    write_json(args.output, dict(record, common_s=common_s, cap_m=cap, names=p.names))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'work', 'upstream', 'atpython', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--arm', choices=('3', '5', 'ATPlace'))
    args = parser.parse_args()
    if args.arm and args.case:
        run_arm(args)
        return
    if args.arm or args.case:
        parser.error('supply both --case and --arm for a single worker')
    args.work.mkdir(parents=True, exist_ok=False)
    if args.output.exists():
        parser.error('use a fresh output path')
    evidence = dict(seed=20261119, cases={case: {} for case in CASES})
    order = [(case, arm) for i, case in enumerate(CASES)
             for arm in (('5', '3') if i % 2 == 0 else ('3', '5'))]
    for case, arm in order + [(case, 'ATPlace') for case in CASES]:
        output = args.work / f'{case}-{arm}.json'
        cmd = [sys.executable, __file__, '--case', case, '--arm', arm, '--output', str(output)]
        for key in ('source', 'work', 'upstream', 'atpython'):
            cmd.extend(('--'+key, str(getattr(args, key))))
        t = perf_counter()
        subprocess.run(cmd, check=True)
        total_s = perf_counter() - t
        row = json.loads(output.read_bytes())
        evidence['cases'][case][arm] = dict(row, total_s=total_s)
        write_json(args.output, evidence)
        print(case, arm, round(row['peak_c'], 6), round(total_s, 3), flush=True)


if __name__ == '__main__':
    main()
