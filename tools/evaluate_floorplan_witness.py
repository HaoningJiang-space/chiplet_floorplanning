"""Verify a new route witness under unchanged frozen physical inputs."""

import argparse
import copy
import json
from pathlib import Path

from chiplet_floorplanning.characterization import digest
from chiplet_floorplanning.floorplanning import evaluate, write_json
from benchmark_floorplanning import compact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark', type=Path)
    parser.add_argument('search', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sta', type=Path, default=Path('local/upstream/OpenSTA/app/sta.exe'))
    parser.add_argument('--model-root', type=Path, default=Path('local/pdk-v03'))
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads((args.benchmark/'frozen-inputs.json').read_text())
    search = json.loads(args.search.read_text())
    if search['status']!='feasible' or search['benchmark_inputs_sha256']!=digest(args.benchmark/'frozen-inputs.json'):
        raise ValueError('route witness not tied to the same frozen benchmark')
    for path, expected in frozen['source_sha256'].items():
        if digest(path)!=expected:
            raise ValueError('benchmark source changed: '+path)
    layout_id = search['layout_id']; layout = frozen['layouts'][layout_id]
    result = dict(complete=False, search_sha256=digest(args.search),
                  benchmark_inputs_sha256=digest(args.benchmark/'frozen-inputs.json'),
                  script_sha256=digest(__file__), cases=[], paired_refinement=[],
                  purpose='feasible_witness_to_close_thermal_bound_not_equal_budget_algorithm_comparison')
    for condition, original in frozen['profiles'].items():
        for factor in ((1, 2, 4) if condition=='nominal' else (1,)):
            cfg = copy.deepcopy(original); cfg['routing']['order'] = search['witness_order']
            if factor>1:
                cfg['grid'] = {**cfg['design']['grid'], 'nx': cfg['design']['grid']['nx']*factor,
                               'ny': cfg['design']['grid']['ny']*factor}
            name = condition+'_'+layout_id+'_witness'+(f'_refine{factor}' if factor>1 else '')
            cfg['runtime'] = dict(output=str(args.output/name), sta=str(args.sta), model_root=str(args.model_root))
            row = evaluate(layout, cfg)
            row.update(id=name, layout_id=layout_id, profile=condition, policy='witness')
            result['cases' if factor==1 else 'paired_refinement'].append(dict(factor=factor, **compact(row)))
            write_json(args.output/'report.json', result)
            print(name, row['status'], row.get('thermal', {}).get('peak_c'), flush=True)
    result['complete'] = True; write_json(args.output/'report.json', result)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
