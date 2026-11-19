"""Choose simultaneous translations using additive heat transfer at the original hotspots."""

import argparse
from dataclasses import replace
from itertools import combinations
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import is_legal
from chiplet_floorplanning.placement.common_move import HotspotResponse, cooling_bounds
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet
from chiplet_floorplanning.placement.relocation import ConnectionCost, Landing, landing_bank
from chiplet_floorplanning.placement.search import rotated_size
from common_relocation import TARGET, ORIGINAL, audit, freeze_action
from direct_relocation import rules
from power_uncertainty import cases, text_digest


def propose(p, start, cap, meta, centres):
    footprint, demand = rules(p,meta)
    costs = ConnectionCost(p,start,demand)
    bank,_ = landing_bank(p,footprint,start,costs)
    stay = bank[0]
    singles = [v for v in bank if len(v.chips)==1 and v.cost<=cap+1e-9]
    sheets = [CooledSheet(p,np.asarray(pos)) for pos in centres.values()]
    base = sheets[0].power_map(start)
    sizes = rotated_size(p,start.rotation_deg)/1000
    rows = [HotspotResponse(sh,base) for sh in sheets]
    old = np.array([r.peak_k for r in rows])
    bounds = np.array([cooling_bounds(singles,start,sizes,p.power_w,r) for r in rows]).T
    chips = np.array([v.chips[0] for v in singles],dtype=int)
    shortlist = set()
    for chip in np.unique(chips):
        options = np.flatnonzero(chips==chip)
        for column in bounds.T:
            shortlist.add(min(options,key=lambda i:(-column[i],singles[i].cost,i)))
    pairs = []
    for i,j in combinations(sorted(shortlist),2):
        if chips[i] != chips[j]:
            optimistic = float((bounds[i]+bounds[j]).min())
            if optimistic > TARGET:
                pairs.append((-optimistic,i,j))

    def gains(point):
        watts = sheets[0].power_map(point.apply(start))
        return old - np.array([sh.temperatures(watts).max() for sh in sheets])

    best = stay
    best_gain = np.zeros(len(sheets))
    parts = []
    checked = 0
    for neg_bound,i,j in sorted(pairs):
        if -neg_bound < best_gain.min()-1e-8 or checked == 24:
            break
        a,b = singles[i],singles[j]
        move = Landing(a.chips+b.chips,a.destinations_um+b.destinations_um,0.,0.)
        lay = move.apply(start)
        if not is_legal(footprint,lay,100):
            continue
        cost = costs.shifted(lay.centre_um-start.centre_um)
        if cost > cap+1e-9:
            continue
        move = replace(move,cost=cost)
        gain = gains(move)
        checked += 1
        assert gain.min() <= -neg_bound+1e-8
        if gain.min()>TARGET and (-gain.min(),cost)<(-best_gain.min(),best.cost):
            best,best_gain,parts = move,gain,[a,b]
    actions = {"pair":freeze_action(best,start,p)}
    worst = {}
    part_gains = {}
    for part,point in enumerate(parts):
        name = f"part{part+1}"
        actions[name] = freeze_action(point,start,p)
        values = gains(point)
        worst[name] = list(centres)[int(values.argmin())]
        part_gains[name] = dict(zip(centres,values))
    return dict(actions=actions,shortlisted_translations=len(shortlist),positive_bound_pairs=len(pairs),
                checked_pairs=checked,model_cooling_k=dict(zip(centres,best_gain)),
                part_model_cooling_k=part_gains,part_worst=worst)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases",type=Path,required=True)
    ap.add_argument("--evidence",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--audit",type=Path)
    args = ap.parse_args()
    path = args.evidence/"expanded-predictions.json"
    expanded = json.loads(path.read_bytes())
    known = expanded["known_xy_mm"]
    centres = known | expanded["held_xy_mm"]
    inputs = json.loads(ORIGINAL.read_bytes())
    report = dict(original_sha256=text_digest(ORIGINAL),expanded_sha256=text_digest(path),cases={})
    if args.audit:
        locked = json.loads(args.audit.read_bytes())
        assert locked["expanded_sha256"]==report["expanded_sha256"] and locked["original_sha256"]==report["original_sha256"]
        report["paired_sha256"] = text_digest(args.audit)
    for (p,designs,meta),anchor in zip(cases(args.cases),inputs["cases"],strict=True):
        _,start,cap = min(designs,key=lambda t:t[0])
        assert p.name==anchor["name"] and meta["bank_sha256"]==anchor["bank_sha256"]
        np.testing.assert_array_equal(start.centre_um,anchor["anchor_xy_um"])
        np.testing.assert_array_equal(start.rotation_deg,anchor["rotation_deg"])
        data = replace(p,power_w=p.power_w*.1),start,cap,meta
        if not args.audit:
            row = propose(*data,known)
        else:
            selected = locked["cases"][p.name]
            if selected["actions"]["pair"]["chips"]:
                configs = {b:["pair"] for b in centres}
                for part,b in selected["part_worst"].items():
                    configs[b].append(part)
                base = audit(*data,selected,grid=64,configs=configs,centres=centres)
                worst = min(centres,key=lambda b:base["conditions"][b]["pair"]["cooling_k"])
                fine = audit(*data,selected,grid=96,configs={worst:("pair",)},centres=centres)
                row = dict(stayed=False,grid64=base,worst96=fine)
            else:
                row = dict(stayed=True)
        report["cases"][p.name] = row
        print(p.name,flush=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")


if __name__ == "__main__":
    main()
