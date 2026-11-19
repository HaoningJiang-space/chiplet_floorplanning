"""Freeze and independently audit one layout under multiple possible cold-plate positions."""

import argparse
from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import is_legal
from chiplet_floorplanning.placement.common_move import HotspotResponse, common_landing, cooling_bounds
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet
from chiplet_floorplanning.placement.relocation import ConnectionCost, landing_bank
from chiplet_floorplanning.placement.search import rotated_size
from chiplet_floorplanning.placement.thermal import solve
from direct_relocation import physical_cost, rebuild, rules
from power_uncertainty import cases, text_digest
from relocation_contact import contact_model


CENTRES = dict(west=(88,100), east=(112,100), south=(100,88), north=(100,112), centre=(100,100))
FOUR = ("west","east","south","north")
PAIR = FOUR[:2]
TARGET = .1
ORIGINAL = Path(__file__).resolve().parents[1] / "docs/evidence/direct-relocation/predictions.json"


def freeze_action(point, start, problem):
    return dict(chips=[problem.names[i] for i in point.chips], indices=point.chips,
                from_um=start.centre_um[list(point.chips)].tolist(), to_um=point.destinations_um, cost=point.cost)


def predict(p, start, cap, meta, prior, *, centres=None):
    pool = {b:CENTRES[b] for b in FOUR} if centres is None else centres
    policies = {"two":PAIR, "four":FOUR} if centres is None else {"expanded":tuple(pool)}
    footprint, demand = rules(p, meta)
    bank, _ = landing_bank(p, footprint, start, ConnectionCost(p, start, demand))
    bank = [v for v in bank if v.cost <= cap+1e-9]
    sizes = rotated_size(p, start.rotation_deg)/1000
    sheets = {b:CooledSheet(p,np.array(xy)) for b,xy in pool.items()}
    base_w = sheets["west"].power_map(start)
    rows = {b:HotspotResponse(sh,base_w) for b,sh in sheets.items()}
    bounds = {b:cooling_bounds(bank,start,sizes,p.power_w,rows[b]) for b in pool}
    costs = [v.cost for v in bank]
    cache = {0:{b:0. for b in pool}}

    def gains(i, boundaries):
        row = cache.setdefault(i,{})
        missing = [b for b in boundaries if b not in row]
        if missing:
            watts = sheets["west"].power_map(bank[i].apply(start))
            for b in missing:
                row[b] = rows[b].peak_k - float(sheets[b].temperatures(watts).max())
        return [row[b] for b in boundaries]

    chosen, checks = {}, {}
    for arm, known in policies.items():
        bound = np.min([bounds[b] for b in known],axis=0)
        if arm == "two":
            i = min(range(len(bank)), key=lambda i:(-bound[i],costs[i],i))
            chosen["old_hot"] = i if bound[i] > TARGET else 0
        result = common_landing(bound,costs,lambda i:min(gains(i,known)),TARGET)
        chosen[arm] = result.index
        checks[arm] = dict(best_model_gain_k=result.best_gain_k, full_candidates=result.checked_moves,
                           could_clear_target=int((bound > TARGET).sum()))
    reused_scores = sum(len(row) for row in cache.values()) - len(pool)
    actions = {k:freeze_action(bank[i],start,p) for k,i in chosen.items()}
    if centres is not None:
        return dict(actions=actions, checks=checks, feasible=len(bank), forward_fields_while_searching=reused_scores)
    exhaustive = {}
    if p.name in ("Case1","micro150"):
        # Independent exhaustive reference: forward fields at every candidate, no bounds or early exit.
        all_gains = np.array([[rows[b].peak_k - sheets[b].peak(v.apply(start)) for b in FOUR] for v in bank])
        for arm, n in (("two",2),("four",4)):
            values = all_gains[:,:n].min(axis=1)
            best = min(range(len(bank)),key=lambda i:(-values[i],costs[i],i))
            picked = best if values[best] > TARGET else 0
            assert picked == chosen[arm] and abs(checks[arm]["best_model_gain_k"]-values[best]) < 1e-8
            exhaustive[arm] = dict(index=picked,best_k=float(values[best]))
    old = prior["groups"]["strict"]["choices"]["direct"]
    actions["half_space"] = {k:old[k] for k in ("chips","indices","from_um","to_um","cost")}
    for a in actions.values():
        lay = rebuild(start,a)
        exact = physical_cost(p,lay,demand)
        assert is_legal(footprint,lay,100) and abs(exact-a["cost"]) < 1e-9 and exact <= cap+1e-9
    return dict(actions=actions, feasible=len(bank), checks=checks, exhaustive=exhaustive,
                forward_fields_while_searching=reused_scores,
                old_hot_bound_k=float(min(bounds[b][chosen["old_hot"]] for b in PAIR)),
                decisions_model_gains_k={a:dict(zip(FOUR,gains(i,FOUR))) for a,i in chosen.items()})


def audit(p, start, cap, meta, pred, *, grid, configs=None, centres=CENTRES):
    footprint, demand = rules(p,meta)
    cache, results = {}, {}
    layouts = {"start": start, **{a:rebuild(start,action) for a,action in pred["actions"].items()}}
    if configs is None:
        configs = {b:tuple(layouts) for b in centres}
    for b, arms in configs.items():
        row = {}
        for arm in ("start",*arms):
            if arm in row:
                continue
            lay = layouts[arm]
            cost = physical_cost(p,lay,demand)
            assert is_legal(footprint,lay,100) and cost <= cap+1e-9
            if arm != "start":
                assert abs(pred["actions"][arm]["cost"]-cost) < 1e-9
            key = b,lay.centre_um.tobytes()
            if key not in cache:
                s,_,_ = solve(contact_model(p,lay,grid,np.array(centres[b],dtype=float)),node_limit=450000)
                cache[key] = dict(peak_c=s["peak_power_layer_c"],residual_w=s["linear_residual_inf_w"],
                                  balance_w=s["energy_balance_error_w"],watts=s["source_power_w"])
            row[arm] = dict(cost=cost,**cache[key])
        for v in row.values():
            v["cooling_k"] = row["start"]["peak_c"]-v["peak_c"]
        results[b] = row
    return dict(conditions=results,distinct_solves=len(cache))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--audit",type=Path)
    args = ap.parse_args()
    original = json.loads(ORIGINAL.read_bytes())
    report = dict(origin_sha256=text_digest(ORIGINAL), boundary_xy_mm=CENTRES, power_fraction=.1,
                  target_k=TARGET, cases={})
    if args.audit:
        locked = json.loads(args.audit.read_bytes())
        assert locked["origin_sha256"] == report["origin_sha256"]
        report["locked_sha256"] = text_digest(args.audit)
    inputs = {}
    for (p,designs,meta), old in zip(cases(args.cases),original["cases"],strict=True):
        index,start,cap = min(designs,key=lambda t:t[0])
        assert index == old["anchor_id"] and p.name == old["name"] and meta["bank_sha256"] == old["bank_sha256"]
        np.testing.assert_array_equal(start.centre_um,old["anchor_xy_um"])
        np.testing.assert_array_equal(start.rotation_deg,old["rotation_deg"])
        p = replace(p,power_w=p.power_w*report["power_fraction"])
        inputs[p.name] = p,start,cap,meta
        row = (audit(*inputs[p.name],locked["cases"][p.name],grid=64) if args.audit
               else predict(*inputs[p.name],old))
        report["cases"][p.name] = dict(family=meta["family"],metric=meta["cost_metric"],cap=cap,**row)
        print(p.name,flush=True)
    if args.audit:
        refined = {}
        for family in ("ATPlace","TAP-2.5D"):
            rows = [(name,r["conditions"]) for name,r in report["cases"].items() if r["family"] == family]
            weak = min(((r[b]["four"]["cooling_k"],name,b) for name,r in rows for b in FOUR),key=lambda x:x[0])
            centre = max(((abs(r["centre"]["four"]["cooling_k"]),name,"centre") for name,r in rows),key=lambda x:x[0])
            for _,name,b in (weak,centre):
                refined.setdefault(name,{})[b] = ("four",)
        report["refined96"] = {n:audit(*inputs[n],locked["cases"][n],grid=96,configs=g) for n,g in refined.items()}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")


if __name__ == "__main__":
    main()
