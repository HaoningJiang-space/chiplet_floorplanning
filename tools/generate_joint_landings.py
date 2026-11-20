"""Generate, time and independently audit joint die moves at the frozen interconnect caps."""

import argparse
from itertools import combinations
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement import is_legal
from chiplet_floorplanning.placement.common_move import HotspotResponse
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet
from chiplet_floorplanning.placement.joint_generation import JointLandings
from chiplet_floorplanning.placement.observer_search import search_observers
from chiplet_floorplanning.placement.relocation import Landing, legal_destinations
from common_relocation import CENTRES, FOUR, TARGET, audit, freeze_action
from direct_relocation import physical_cost, rebuild, rules
from power_uncertainty import text_digest
from transfer_placement import JointSelection, PRIOR, run_method, starting_cases


OLD_TIMING = PRIOR.parent / "transfer-bound/timing.json"
METHODS = ("feedback", "adaptive", "fixed", "singles", "matched", "protected", "contacts", "contacts_matched")
EPS = 1e-8


def thermal_start(p, start):
    sheets = [CooledSheet(p, np.asarray(CENTRES[b])) for b in FOUR]
    watts = sheets[0].power_map(start)
    return sheets, [sh.temperatures(watts) for sh in sheets]


def score_layout(sheets, old_peaks, layout):
    watts = sheets[0].power_map(layout)
    gains, cells = [], []
    for sh, old in zip(sheets, old_peaks):
        final = sh.temperatures(watts)
        y, x = np.unravel_index(final.argmax(), final.shape)
        cells.append((int(y), int(x)))
        gains.append(float(old - final[y, x]))
    return gains, cells


def generate(p, start, cap, meta, allowance, adaptive, preserve_previous=False, retain_contacts=False):
    footprint, demand = rules(p, meta)
    pool = JointLandings(p, footprint, start, demand, cap)
    stay = Landing((), (), pool.net.initial, 0.)
    chosen = stay
    best = (0., float(stay.cost), ())
    checked, previous, history = set(), [], []
    if preserve_previous:
        old = JointSelection(p, start, cap, meta)
        sheets, initial = old.sheets, old.fields
        lookup = {(int(c), tuple(xy)):k for k, (c, xy) in enumerate(zip(pool.chip, pool.xy))}
        def old_key(move):
            return tuple(sorted(lookup[c, xy] for c, xy in zip(move.chips, move.destinations_um)))
        def verify_old(i):
            gain, cell = old.verify(i)
            move = old.bank[i]
            checked.add(old_key(move))
            previous.append(dict(action=freeze_action(move, start, p), gain_k=gain))
            return gain, cell
        result = search_observers(old.old_upper, old.costs, verify_old, old.observe)
        chosen = old.bank[result.best]
        best = (-result.best_gain_k, chosen.cost, old_key(chosen))
    else:
        sheets, initial = thermal_start(p, start)
    peaks = [float(v.max()) for v in initial]
    old_cells = [np.unravel_index(v.argmax(), v.shape) for v in initial]
    probes = set()

    def observe(b, cell):
        pool.observe(HotspotResponse.at_cell(sheets[b], initial[b], cell))
        probes.add((b, cell))

    for b, cell in enumerate(old_cells):
        observe(b, cell)
    if retain_contacts:
        pool.retain_contact_landings()
    stop = "budget"
    assert len(checked) <= allowance
    for _ in range(allowance-len(checked)):
        candidate = pool.propose(checked, -best[0])
        if candidate is None:
            stop = "no_contender"
            break
        key, move, upper = candidate
        checked.add(key)
        gains, cells = score_layout(sheets, peaks, move.apply(start))
        b = int(np.argmin(gains))
        gain = gains[b]
        assert gain <= upper + EPS
        rank = (-gain, move.cost, key)
        if rank < best:
            best, chosen = rank, move
        new_probe = adaptive and (b, cells[b]) not in probes and gain < upper - EPS
        if new_probe:
            observe(b, cells[b])
        history.append(dict(action=freeze_action(move, start, p), upper_k=upper, gains_k=gains,
                            limiting_boundary=FOUR[b], cell_yx=cells[b], added=bool(new_probe)))
    raw = chosen
    if -best[0] <= TARGET:
        chosen = stay
    return dict(action=freeze_action(chosen, start, p), raw_action=freeze_action(raw, start, p),
                gain_k=-best[0] if chosen.chips else 0., raw_k=-best[0], cap=cap,
                metric=meta["cost_metric"], starting_peaks_above_ambient_k=peaks, budget=allowance,
                joint_evaluations=len(checked), new_probes=len(probes)-4,
                prior_extra_probes=old.adjoints if preserve_previous else 0, prior_checks=previous,
                scored_pairs=pool.scored_pairs, lattice_landings=len(pool.xy), stop=stop, trace=history)


def timing(source, repeat):
    # Only two integer counts per case from the published comparator cross into generation.
    old = json.loads(OLD_TIMING.read_bytes())["runs"]["feedback"][0]["cases"]
    limits = {n:(r["candidates"], r["forwards"]//4) for n, r in old.items()}
    cases, times = {}, {m:[] for m in METHODS}
    for t in range(repeat):
        order = t*2 % len(METHODS)
        methods = METHODS[order:] + METHODS[:order]
        for method in methods:
            if method in ("feedback", "singles"):
                r = run_method(source, method)
                total, records = r["total_s"], {}
                per_case = {}
                for n, row in r["cases"].items():
                    records[n] = dict(action=row["action"], gain_k=row["decision_gain_k"] if row["selected"] else 0.,
                                      raw_k=row["decision_gain_k"], cap=row["cap"], metric=row["metric"],
                                      joint_evaluations=row["forwards"]//4 if method=="feedback" else row["joint_checks"],
                                      joint_fields=row["forwards"], single_fields=row["single_fields"],
                                      new_probes=row["adjoints"], budget=row["candidates"])
                    per_case[n] = row["prepare_s"] + row["score_s"]
            else:
                begin = previous = perf_counter()
                records, per_case = {}, {}
                for p, start, cap, meta in starting_cases(source):
                    n = p.name
                    limit = limits[n][1 if method in ("matched","contacts_matched") else 0]
                    records[n] = generate(p, start, cap, meta, limit, method != "fixed",
                                          preserve_previous=method == "protected",
                                          retain_contacts=method in ("contacts","contacts_matched"))
                    now = perf_counter()
                    per_case[n] = now-previous
                    previous = now
                total = perf_counter()-begin
            if t == 0:
                cases[method] = records
            else:
                assert records == cases[method]
            times[method].append(dict(total_s=total, by_case_s=per_case))
            print(t+1, method, round(total, 3), flush=True)
    return dict(base_commit="7c94537", previous_timing_sha256=text_digest(OLD_TIMING),
                seed=20261119, threshold_k=TARGET, cost_and_check_counts=limits, cases=cases, times=times)


def action_key(action):
    return tuple(sorted(zip(action["indices"], map(tuple, action["to_um"]))))


def exhaustive(p, start, cap, footprint, demand, sheets, peaks):
    # Independently enumerate both endpoints; no single thermal/cost shortlist.
    sites = [(c, tuple(xy)) for c in range(p.count)
             for xy in legal_destinations(footprint, start, c, 100, 1000)]
    best = (0., cap, ())
    winner = Landing((), (), cap, 0.)
    count = 0
    for (a, x), (b, y) in combinations(sites, 2):
        if a == b:
            continue
        move = Landing((a,b), (x,y), 0., 0.)
        layout = move.apply(start)
        cost = physical_cost(p, layout, demand)
        if cost > cap + 1e-9 or not is_legal(footprint, layout, 100):
            continue
        count += 1
        gain = min(score_layout(sheets, peaks, layout)[0])
        rank = (-gain, cost, (a,x,b,y))
        if rank < best:
            best = rank
            winner = Landing((a,b), (x,y), cost, 0.)
    return dict(feasible=count, gain_k=-best[0], action=freeze_action(winner, start, p))


def explain_pair(start, action, demand, sheets, initial):
    """At the actual limiting cell split the final margin into signed contributions."""
    peaks = [float(field.max()) for field in initial]
    gains, cells = score_layout(sheets, peaks, rebuild(start, action))
    b = int(np.argmin(gains))
    cell = cells[b]
    headroom = float(peaks[b] - initial[b][cell])
    parts = []
    for chip, xy in zip(action["indices"], action["to_um"]):
        layout = Landing((chip,), (tuple(xy),), 0., 0.).apply(start)
        watts = sheets[0].power_map(layout)
        fields = [sh.temperatures(watts) for sh in sheets]
        parts.append(dict(chip=sheets[0].problem.names[chip], cost=physical_cost(sheets[0].problem, layout, demand),
                          gain_alone_k=min(float(pk-f.max()) for pk, f in zip(peaks, fields)),
                          change_at_cell_k=float(fields[b][cell]-initial[b][cell])))
    assert abs(headroom-sum(v["change_at_cell_k"] for v in parts)-min(gains)) < EPS
    return dict(boundary=FOUR[b], cell_yx=cell, headroom_k=headroom, parts=parts)


def missed_pair(p, start, cap, footprint, demand, sheets, fields, previous, trace):
    """Replay observed rows to see whether the old winner could even be proposed."""
    domain = JointLandings(p, footprint, start, demand, cap)
    lookup = {(int(chip), tuple(xy)):i for i, (chip, xy) in enumerate(zip(domain.chip, domain.xy))}
    key = [lookup[k] for k in action_key(previous)]
    for sh, field in zip(sheets, fields):
        cell = np.unravel_index(field.argmax(), field.shape)
        domain.observe(HotspotResponse.at_cell(sh, field, cell))
    stages = []
    for step in [*trace, None]:
        stages.append(dict(reachable=bool(set(key).intersection(domain.anchors())),
                           upper_k=min(h+c[key].sum() for h,c in zip(domain.headroom, domain.cooling))))
        if step and step["added"]:
            b = FOUR.index(step["limiting_boundary"])
            domain.observe(HotspotResponse.at_cell(sheets[b], fields[b], tuple(step["cell_yx"])))
    return stages


def neighbours(p, start, cap, footprint, demand, chosen, sites, tested):
    for i, chip in enumerate(chosen["indices"]):
        for dx, dy in ((-1000,0), (1000,0), (0,-1000), (0,1000)):
            xy = list(map(tuple, chosen["to_um"]))
            xy[i] = (xy[i][0]+dx, xy[i][1]+dy)
            if (chip, xy[i]) not in sites:
                continue
            move = Landing(tuple(chosen["indices"]), tuple(xy), 0., 0.)
            layout = move.apply(start)
            cost = physical_cost(p, layout, demand)
            if cost <= cap+1e-9 and is_legal(footprint, layout, 100):
                action = dict(freeze_action(move, start, p), cost=cost)
                if action_key(action) not in tested:
                    yield action


def check(source, file):
    search = json.loads(file.read_bytes())
    archive = json.loads((PRIOR/"selection.json").read_bytes())
    report = dict(search_sha256=text_digest(file), previous_pool_sha256=text_digest(PRIOR/"selection.json"), cases={})
    largest_improvement = EPS
    challenge_case = None
    for p, start, cap, meta in starting_cases(source):
        original = archive["cases"][p.name]
        pool = {action_key(a):a for a in original["candidates"]}
        old_move = original["candidates"][original["methods"]["full"]["selected"]]
        sheets, fields = thermal_start(p, start)
        peaks = [float(f.max()) for f in fields]
        footprint, demand = rules(p, meta)
        cache = {}
        def verify(a):
            key = action_key(a)
            if key not in cache:
                layout = rebuild(start, a)
                cost = physical_cost(p, layout, demand)
                assert is_legal(footprint, layout, 100) and cost <= cap+1e-9 and abs(cost-a["cost"]) < 1e-9
                cache[key] = score_layout(sheets, peaks, layout)[0]
            return cache[key]
        methods, actions = {}, {"previous":old_move}
        for arm, rows in search["cases"].items():
            row = rows[p.name]
            a = row["action"]
            gains = verify(a)
            assert abs(min(gains)-row["gain_k"]) < EPS
            trace = row.get("trace", [])
            for step in trace:
                np.testing.assert_allclose(verify(step["action"]), step["gains_k"], atol=EPS, rtol=0)
            if arm in ("feedback", "singles"):
                assert action_key(a) == action_key(old_move)
                available = [(s["cost"], s["full_gain_k"]) for s in pool.values()]
            else:
                available = [(s["action"]["cost"], min(s["gains_k"])) for s in trace]
                previous = row["prior_checks"]
                for s in previous:
                    assert abs(min(verify(s["action"]))-s["gain_k"]) < EPS
                    available.append((s["action"]["cost"], s["gain_k"]))
                assert len(trace)+len(previous) == row["joint_evaluations"] <= row["budget"] <= 24
                if arm == "protected":
                    assert min(gains) >= min(verify(old_move))-EPS
            passing = [v for v in available if v[1] > TARGET]
            methods[arm] = dict(gain_k=min(gains), cost=a["cost"], outside=action_key(a) not in pool,
                                novel_proposals=sum(action_key(s["action"]) not in pool for s in trace),
                                peak_above_ambient_k=dict(zip(FOUR, np.subtract(peaks,gains))),
                                cheapest_passing_cost=min(passing)[0] if passing else None)
            if arm in ("adaptive","fixed","matched","protected","contacts","contacts_matched"):
                actions[arm] = a
        package = audit(p,start,cap,meta,dict(actions=actions),grid=64)
        summary = {}
        for arm in actions:
            cooling = {b:r[arm]["cooling_k"] for b,r in package["conditions"].items()}
            summary[arm] = dict(four_k=min(cooling[b] for b in FOUR), centre_k=cooling["centre"], by_condition_k=cooling)
        result = dict(methods=methods, package=summary, max_energy_balance_w=max(
            abs(v["balance_w"]) for r in package["conditions"].values() for v in r.values()))
        domain = JointLandings(p, footprint, start, demand, cap)
        for sh, field in zip(sheets, fields):
            domain.observe(HotspotResponse.at_cell(sh, field, np.unravel_index(field.argmax(), field.shape)))
        domain.retain_contact_landings()
        ids = {(int(chip), tuple(xy)):i for i, (chip, xy) in enumerate(zip(domain.chip, domain.xy))}
        for key in pool:
            if key:
                i, j = [ids[site] for site in key]
                assert ((i in domain.retained and j in domain.partners(i)[0])
                        or (j in domain.retained and i in domain.partners(j)[0]))
        result["old_pairs_covered_by_retained_landings"] = len(pool)-1
        trace = search["cases"]["contacts"][p.name]["trace"]
        tested = {action_key(step["action"]) for step in trace}
        nearby = []
        for a in neighbours(p, start, cap, footprint, demand, actions["contacts"], ids, tested):
            gain = min(verify(a))
            difference = gain-methods["contacts"]["gain_k"]
            nearby.append(dict(action=a, gain_k=gain, improvement_k=difference, outside_old=action_key(a) not in pool))
            if difference > largest_improvement:
                largest_improvement = difference
                challenge_case = p, start, cap, meta, dict(actions=dict(chosen=actions["contacts"], neighbour=a))
        result["one_step_challenge"] = nearby
        if search["cases"]["contacts"][p.name]["stop"] == "no_contender":
            assert methods["contacts"]["gain_k"] >= methods["feedback"]["gain_k"] - EPS
        if actions["adaptive"]["indices"]:
            result["pair_at_limiting_cell"] = explain_pair(start, actions["adaptive"], demand, sheets, fields)
        if actions["contacts"]["indices"]:
            result["contact_pair_at_limiting_cell"] = explain_pair(start, actions["contacts"], demand, sheets, fields)
        if methods["feedback"]["gain_k"] > methods["adaptive"]["gain_k"] + EPS:
            result["previous_winner_during_generation"] = missed_pair(
                p, start, cap, footprint, demand, sheets, fields, old_move, search["cases"]["adaptive"][p.name]["trace"])
        if p.name == "Case5":
            result["exhaustive"] = exhaustive(p, start, cap, footprint, demand, sheets, peaks)
        report["cases"][p.name] = result
        print(p.name, flush=True)
    if challenge_case is not None:
        report["challenge_case"] = challenge_case[0].name
        report["challenge_package"] = audit(*challenge_case, grid=64)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    report = check(args.cases, args.audit) if args.audit else timing(args.cases, args.repeat)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
