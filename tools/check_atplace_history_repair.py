"""Zero-heat exact-reference acceptance on all historical and frozen-pool inputs."""
from pathlib import Path

from atplace_incremental_pins import IncidentPinRepair
from atplace_orientation_repair import prepare as reference
from atplace_search import identities
from run_atplace_orientation import INPUT, PLAN, check_plan
from run_atplace_routing_boundary import read
from run_atplace_search import digest, object_hash, raw, write_new
from run_atplace_temperature_feedback import HISTORY_PATHS


def check(output):
    source, plan = check_plan(INPUT, PLAN)
    inputs = {}
    for path in HISTORY_PATHS:
        for record in read(path)['records']:
            for row in record['rows']:
                key = object_hash(identities(source, row['placement'], plan['gap_um'])[0])
                inputs.setdefault(key, row['placement'])
    historical_count = len(inputs)
    for c in plan['candidates']:
        inputs.setdefault(object_hash(identities(source, c['placement'], plan['gap_um'])[0]), c['placement'])
    engine = IncidentPinRepair(source, plan['gap_um'])
    fields = ('placement', 'layout_key', 'thermal_key', 'routing', 'pin_length_m',
              'pin_length_um_decimal', 'before_pin_length_m', 'trials')
    rows = []
    for i, (key, poses) in enumerate(inputs.items()):
        old = reference(source, poses, plan, True)
        new = engine.prepare(poses, plan['resources'])
        if any(old[k] != new[k] for k in fields):
            raise ValueError('Exact reference disagreement at '+key)
        rows.append(dict(input_layout_sha256=key, exact_match=True, decisions_sha256=object_hash(new['trials']),
                         reference_seconds=old['preparation_seconds'], incremental_seconds=new['preparation_seconds']))
        if (i+1) % 50 == 0:
            print('exactly matched', i+1, 'of', len(inputs), flush=True)
    write_new(output, dict(status='all_historical_and_pool_inputs_exactly_match', new_thermal_queries=0,
                           historical_unique_inputs=historical_count, checked_inputs=len(rows), records=rows,
                           operator_sha256=digest(raw('tools/atplace_incremental_pins.py')),
                           validation_source_sha256=digest(raw(__file__)),
                           history_sha256={p: digest(raw(p)) for p in HISTORY_PATHS},
                           original_plan_sha256=digest(raw(PLAN))))
    print('passed', len(rows), 'inputs; no new heat queries', flush=True)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    check(p.parse_args().output)
