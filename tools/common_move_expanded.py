"""Make one shared landing decision over all thirteen prescribed cold-plate locations."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from common_relocation import CENTRES, ORIGINAL, TARGET, audit, predict
from power_uncertainty import cases, text_digest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases",type=Path,required=True)
    ap.add_argument("--evidence",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--audit",type=Path)
    args = ap.parse_args()
    orig = json.loads(ORIGINAL.read_bytes())
    four_path = args.evidence/"predictions.json"
    prior = json.loads(four_path.read_bytes())
    diagonal = json.loads((args.evidence/"holdout.json").read_bytes())
    assert diagonal["locked_sha256"] == text_digest(four_path) and prior["origin_sha256"] == text_digest(ORIGINAL)
    known = CENTRES | diagonal["diagonal_centres_mm"]
    centres = known | {"held_3_-9":(103,91), "held_-9_3":(91,103)}
    report = dict(four_sha256=text_digest(four_path), known_xy_mm=known, held_xy_mm={b:centres[b] for b in centres if b not in known},
                  cases={})
    if args.audit:
        locked = json.loads(args.audit.read_bytes())
        assert locked["four_sha256"] == report["four_sha256"] and locked["known_xy_mm"] == json.loads(json.dumps(known))
        report["expanded_sha256"] = text_digest(args.audit)
    for (p,designs,meta), anchor in zip(cases(args.cases),orig["cases"],strict=True):
        _,start,cap = min(designs,key=lambda t:t[0])
        assert p.name == anchor["name"] and abs(cap-prior["cases"][p.name]["cap"]) < 1e-9
        np.testing.assert_array_equal(start.centre_um,anchor["anchor_xy_um"])
        row = prior["cases"][p.name]
        inputs = replace(p,power_w=.1*p.power_w),start,cap,meta
        limit = row["checks"]["four"]["best_model_gain_k"]
        if not args.audit:
            if limit <= TARGET:
                report["cases"][p.name] = dict(stayed=True, inherited_upper_k=limit)
            else:
                result = predict(*inputs,anchor,centres=known)
                assert result["checks"]["expanded"]["best_model_gain_k"] <= limit+1e-8
                report["cases"][p.name] = dict(stayed=not bool(result["actions"]["expanded"]["chips"]),**result)
            continue
        selection = locked["cases"][p.name]
        if selection["stayed"]:
            report["cases"][p.name] = dict(stayed=True)
        else:
            base = audit(*inputs,selection,grid=64,configs={b:("expanded",) for b in centres},centres=centres)
            worst = min(base["conditions"],key=lambda b:base["conditions"][b]["expanded"]["cooling_k"])
            fine = audit(*inputs,selection,grid=96,configs={worst:("expanded",)},centres=centres)
            report["cases"][p.name] = dict(stayed=False,grid64=base,worst96=fine)
        if p.name == "ascend910":
            added = diagonal["cases"][p.name]["additional64"]["conditions"]
            worst = min((b for b in added if b.startswith("6/")),key=lambda b:added[b]["four"]["cooling_k"])
            x,y = known[worst]
            adjacent = (worst,"east" if x>100 else "west","north" if y>100 else "south")
            report["interpolation_check"] = {g:audit(*inputs,row,grid=g,configs={b:("four",) for b in adjacent},centres=centres)
                                              for g in (96,128)}
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")


if __name__ == "__main__":
    main()
