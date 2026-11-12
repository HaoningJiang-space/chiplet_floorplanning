"""Run a pin-aware three-chiplet placement through the unified local evaluator."""

import argparse
import json
from pathlib import Path

from chiplet_floorplanning.floorplanning import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('configuration', type=Path)
    parser.add_argument('--layout', type=Path, help='placement map, keyed by die ID')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sta', type=Path, default=Path('local/upstream/OpenSTA/app/sta.exe'))
    parser.add_argument('--model-root', type=Path, default=Path('local/pdk-v03'))
    args = parser.parse_args()
    cfg = json.loads(args.configuration.read_text())
    cfg['runtime'] = dict(output=str(args.output), sta=str(args.sta), model_root=str(args.model_root))
    result = evaluate(json.loads(args.layout.read_text()) if args.layout else {}, cfg)
    print(result['status'], result.get('reason', ''))
    if 'thermal' in result:
        print('Peak temperature C:', result['thermal']['peak_c'])
    for mode, timing in result.get('timing', {}).items():
        print(mode, timing['status'], timing.get('worst_setup_ns'), timing.get('worst_hold_ns'), timing.get('reason', ''))
    return 0 if result['status']=='analyzed' else 1


if __name__=='__main__':
    raise SystemExit(main())
