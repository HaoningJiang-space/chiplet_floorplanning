"""Zero-heat equivalence and cost check against every frozen B/D local input."""
import argparse
from pathlib import Path
import subprocess

from atplace_incremental_pins import IncidentPinRepair
from atplace_orientation_repair import prepare as reference
from run_atplace_orientation import INPUT, PLAN, check_plan
from run_atplace_search import digest, raw, write_new


def check(input_path, plan_path, output):
    source, plan = check_plan(input_path, plan_path)
    engine = IncidentPinRepair(source, plan['gap_um'])
    inputs = [(a['label'], a['placement']) for a in plan['anchors']]
    inputs.extend((c['candidate_id'], c['placement']) for c in plan['candidates'])
    records = []
    fields = ('placement', 'layout_key', 'thermal_key', 'routing', 'pin_length_m',
              'pin_length_um_decimal', 'before_pin_length_m', 'trials')
    for name, poses in inputs:
        old = reference(source, poses, plan, True)
        new = engine.prepare(poses, plan['resources'])
        if any(old[k] != new[k] for k in fields):
            raise ValueError('Exact orientation/pins/routing mismatch: '+name)
        records.append(dict(candidate_id=name, exact_match=True,
                            reference_net_length_evaluations=old['pin_evaluations']*len(source['nets']),
                            incremental_net_length_evaluations=new['effort']['net_length_evaluations'],
                            reference_seconds=old['preparation_seconds'], incremental_seconds=new['preparation_seconds'],
                            repaired_pin_length_m=new['pin_length_m'],
                            length_slack_m=plan['length_cap_m']-new['pin_length_m']))
    result = dict(status='exact_reference_equivalence_passed', new_thermal_queries=0,
                  analyzed_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                  input_sha256=digest(raw(input_path)), parent_plan_sha256=digest(raw(plan_path)),
                  source_sha256={p: digest(raw(p)) for p in ('tools/atplace_incremental_pins.py', 'tools/check_atplace_incremental_pins.py')},
                  records=records, setup_seconds=engine.setup_seconds,
                  reference_total_seconds=sum(r['reference_seconds'] for r in records),
                  incremental_total_seconds=engine.setup_seconds+sum(r['incremental_seconds'] for r in records),
                  reference_net_length_evaluations=sum(r['reference_net_length_evaluations'] for r in records),
                  incremental_net_length_evaluations=sum(r['incremental_net_length_evaluations'] for r in records),
                  note='One local timing observation; exact output and operation-count equivalence are the acceptance criteria')
    write_new(output, result)
    print({k: v for k, v in result.items() if k not in ('records', 'source_sha256')})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, default=Path(INPUT))
    p.add_argument('--plan', type=Path, default=Path(PLAN))
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    check(a.input, a.plan, a.output)
