"""Expose the five locked four-direction moves to intermediate and extrapolated cold plates."""

import argparse
from dataclasses import replace
from itertools import product
import json
from pathlib import Path

from common_relocation import CENTRES, ORIGINAL, audit
from power_uncertainty import cases, text_digest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    locked = json.loads(args.predictions.read_bytes())
    scored = json.loads(args.package.read_bytes())
    assert locked["origin_sha256"] == text_digest(ORIGINAL) and scored["locked_sha256"] == text_digest(args.predictions)
    diagonals = {f"{distance}/{x},{y}":(100+x*distance,100+y*distance)
                 for distance in (6,12) for x,y in product((-1,1),repeat=2)}
    report = dict(locked_sha256=text_digest(args.predictions), package_sha256=text_digest(args.package),
                  diagonal_centres_mm=diagonals, cases={})
    for p,designs,meta in cases(args.cases):
        selection = locked["cases"][p.name]
        if not selection["actions"]["four"]["chips"]:
            report["cases"][p.name] = dict(stayed=True)
            continue
        _,start,cap = min(designs,key=lambda t:t[0])
        inputs = replace(p,power_w=p.power_w*locked["power_fraction"]),start,cap,meta,selection
        extra = audit(*inputs, grid=64, configs={b:("four",) for b in diagonals}, centres=diagonals)
        scores = scored["cases"][p.name]["conditions"] | extra["conditions"]
        worst = min(scores,key=lambda b:scores[b]["four"]["cooling_k"])
        fine = audit(*inputs, grid=96, configs={worst:("four",)}, centres=CENTRES | diagonals)
        report["cases"][p.name] = dict(stayed=False, additional64=extra, worst_contact=worst, worst96=fine)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")


if __name__ == "__main__":
    main()
