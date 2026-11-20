"""Time all-die, two-die and previously anchored decisions from the same parsed holdout."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from solve_joint_margin import HOLDOUT, baseline, choose, inputs
from power_uncertainty import text_digest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", required=True,type=Path)
    ap.add_argument("--output", required=True,type=Path)
    args = ap.parse_args()
    data = next(v for v in inputs(args.cases,True) if v[0].name=="RC-mesh-3x4")
    methods = ("previous","pair","all")
    times = {arm:[] for arm in methods}
    for t in range(3):
        for arm in methods[t:]+methods[:t]:
            then=perf_counter()
            if arm=="previous":
                r=baseline(*data)
            elif arm=="pair":
                r=choose(*data,4,sparse=True)
            else:
                r=choose(*data,4,sparse=True,cardinality=(1,data[0].count),time_limit_s=5.)
            elapsed=perf_counter()-then
            assert r["checks"]==4
            times[arm].append(dict(elapsed_s=elapsed,gain_k=r["gain_k"],action=r["action"],
                                   checks=r["checks"],incomplete=r.get("incomplete_master",False)))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(holdout_sha256=text_digest(HOLDOUT),case=data[0].name,
        cap=data[2],runs=times),indent=2,allow_nan=False)+"\n",encoding="utf8",newline="\n")


if __name__=="__main__":
    main()
