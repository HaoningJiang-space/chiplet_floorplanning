"""Bounded deterministic order search; failure remains unknown, never a proof."""

import argparse
import json
from pathlib import Path
import random

from chiplet_floorplanning.characterization import digest
from chiplet_floorplanning.floorplanning import write_json
from chiplet_floorplanning.layout import relocate_design
from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.pin_fabric import pin_fabric
from chiplet_floorplanning.routing_graph import route_greedy
from validation.sources import git_revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark', type=Path)
    parser.add_argument('--layout-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--budget', type=int, default=64)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads((args.benchmark/'frozen-inputs.json').read_text())
    cfg = frozen['profiles']['nominal']; layout = frozen['layouts'][args.layout_id]
    case = relocate_design(parse_case(cfg['design']), layout)
    fabric, nets, _ = pin_fabric(case, cfg['routing']); names = [n.name for n in nets]
    rng = random.Random(20261111); orders = []
    for _ in range(args.budget):
        order = names.copy(); rng.shuffle(order); orders.append(order)
    result = dict(benchmark_inputs_sha256=digest(args.benchmark/'frozen-inputs.json'),
                  layout_id=args.layout_id, source=git_revision(Path('.')), script_sha256=digest(__file__),
                  candidate_orders=orders, attempts=[], status='search_failed', proven_infeasible=False)
    write_json(args.output/'frozen-search.json', result)
    for order in orders:
        routed = route_greedy(fabric, nets, order)
        result['attempts'].append(dict(order=order, status=routed['status'], failed_net=routed.get('failed_net')))
        print(len(result['attempts']), routed['status'], routed.get('failed_net'), flush=True)
        if routed['status']=='feasible':
            result.update(status='feasible', witness_order=order, witness_audit=routed['audit'])
            break
    write_json(args.output/'report.json', result)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
