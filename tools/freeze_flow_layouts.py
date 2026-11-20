"""Select two interconnect-admissible layouts per case without reading new thermal fields."""
import argparse
import json
from hashlib import sha256
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem
from chiplet_floorplanning.placement.lp import legalize_relations
from chiplet_floorplanning.placement.pin_reach import PinReachCell
from continuous_baseline_audit import escape_util
from continuous_reach_geometry import cycle_audit, inspect, limits, rectangular_audit, repair_orders
from compare_large_pool import write_json

EVIDENCE = Path(__file__).resolve().parents[1] / 'docs/evidence'


def freeze(source):
    archive = json.loads((EVIDENCE / 'cold-plate-joint-v1.json').read_bytes())
    hashes = {r['case']: r['input_sha256'] for r in
              json.loads((EVIDENCE / 'layout-dominance-v1.json').read_bytes())['cases']}
    results = {}
    for name, key in [('Case9', '1.25'), ('Case3', '1.1')]:
        raw = (source / (name+'.json')).read_bytes()
        assert sha256(raw).hexdigest() == hashes[name]
        p = Problem.from_imported(json.loads(raw))
        old = next(c for c in archive['cases'] if c['case'] == name)
        cap = old['caps_m'][key]
        reach = limits(p) if name == 'Case9' else np.full(len(p.pin_chip), 25.)
        proof = None
        if name == 'Case3':
            native = np.full(len(reach), 2.)
            proof = cycle_audit(p, native)
            nodes, witness = rectangular_audit(p, native, proof['surviving_turns'])
            proof.update(separation_nodes=nodes, feasible=witness is not None)
            assert witness is None
        def target(factor):
            row = old['rows'][factor]
            return Layout(np.array(row['joint_centre_um']), np.array(row['joint_rotation_deg']))
        first, second = target(key), target('1.0')
        reference = first if name == 'Case9' else second
        legal = legalize_relations(p, reference, 100)
        cell = PinReachCell(p, legal, 100, reach, cap)
        anchor = cell.toward(reference.centre_um)
        if anchor is None:
            anchor, _ = repair_orders(p, legal, reach, cap)
        if anchor is None:
            raise ValueError(f'{name}: no admissible reference')
        cell = PinReachCell(p, anchor, 100, reach, cap)
        poses = {}
        for label, ref in [('A', first), ('B', second)]:
            lay = cell.toward(ref.centre_um)
            if lay is None:
                raise ValueError(f'{name}/{label}: no admissible projection')
            metrics = inspect(p, lay, reach, cap)
            escape = escape_util(p, lay)
            assert metrics['feasible'] and escape <= 1.
            poses[label] = dict(**metrics, bin_escape_utilization=escape, centre_um=lay.centre_um.tolist(),
                                rotation_deg=lay.rotation_deg.tolist(),
                                count_over_original_2mm=(inspect(p, lay, np.full(len(reach),2.),cap)['reach_violations']
                                                         if proof else None))
        delta = np.array(poses['A']['centre_um']) - np.array(poses['B']['centre_um'])
        assert np.max(np.ptp(delta, axis=0)) > 1.
        results[name] = dict(source_sha256=hashes[name], cap_m=cap, gap_um=100, names=list(p.names),
                             reach_mm=reach.tolist(), poses=poses, original_interface_proof=proof,
                             source_factors=[key,'1.0'])
    return dict(seed=archive['seed'], base_commit='ff3cb632b4cdc8fdb42958130076864acad0e34b', cases=results)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    write_json(args.output, freeze(args.source))
