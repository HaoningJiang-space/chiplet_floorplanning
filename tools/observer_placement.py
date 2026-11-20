"""Compare sparse observer decisions with exhaustive whole-sheet joint placement decisions."""

import argparse
from dataclasses import replace
from itertools import combinations
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement import is_legal
from chiplet_floorplanning.placement.common_move import HotspotResponse, cooling_bounds
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet
from chiplet_floorplanning.placement.observer_search import hot_cells, search_observers
from chiplet_floorplanning.placement.relocation import ConnectionCost, Landing, legal_destinations
from chiplet_floorplanning.placement.search import rotated_size
from common_relocation import CENTRES, FOUR, ORIGINAL, TARGET, audit, freeze_action
from direct_relocation import physical_cost, rules
from power_uncertainty import cases, text_digest


def joint_bank(problem, start, cap, meta, rows, sizes, *, outside=False):
    footprint, demand = rules(problem, meta)
    rotated_footprints = rotated_size(footprint, start.rotation_deg)
    net = ConnectionCost(problem, start, demand)
    singles = []
    for chip in range(problem.count):
        xy = legal_destinations(footprint, start, chip, 100, 1000)
        costs = net.translations(chip, xy - start.centre_um[chip])
        singles.extend(Landing((chip,), (tuple(pos),), float(cost), 0.)
                       for pos, cost in zip(xy, costs) if cost <= cap + 1e-9)
    gains = np.array([cooling_bounds(singles, start, sizes, problem.power_w, row) for row in rows])
    shortlist = set()
    chips = np.array([v.chips[0] for v in singles], dtype=int)
    for chip in np.unique(chips):
        options = np.flatnonzero(chips == chip)
        for column in gains:
            shortlist.add(min(options, key=lambda i: (-column[i], singles[i].cost, i)))
    pairs = []
    for i, j in combinations(sorted(shortlist), 2):
        a, b = singles[i], singles[j]
        if a.chips == b.chips:
            continue
        # Both destinations were checked against every stationary chip. Only the
        # mutual clearance of the two moving footprints remains to be checked.
        extent = (rotated_footprints[chips[i]] + rotated_footprints[chips[j]]) / 2
        if np.all(abs(np.subtract(a.destinations_um[0], b.destinations_um[0])) < extent + 100):
            continue
        move = Landing(a.chips + b.chips, a.destinations_um + b.destinations_um, 0., 0.)
        layout = move.apply(start)
        cost = net.shifted(layout.centre_um - start.centre_um)
        if cost <= cap + 1e-9:
            pairs.append((float((gains[:, i] + gains[:, j]).min()), replace(move, cost=cost)))
    ranked = sorted(range(len(pairs)), key=lambda k: (-pairs[k][0], pairs[k][1].cost, k))
    chosen = ranked[:16]
    extra = sorted(ranked[16:], key=lambda k: (pairs[k][1].cost, -pairs[k][0], k))
    chosen += extra[:8]
    if outside:
        original = set(chosen)
        chosen = [k for k in ranked if k not in original][:8]
    stay = Landing((), (), net.initial, 0.)
    bank = [stay] + [pairs[k][1] for k in chosen]
    for move in bank:
        layout = move.apply(start)
        assert is_legal(footprint, layout, 100)
        assert abs(physical_cost(problem, layout, demand)-move.cost) < 1e-9
    return bank, np.array([0.] + [pairs[k][0] for k in chosen]), len(pairs)


def compare(problem, start, cap, meta):
    then = perf_counter()
    sheets = [CooledSheet(problem, np.array(CENTRES[b])) for b in FOUR]
    watts = sheets[0].power_map(start)
    fields = [sheet.temperatures(watts) for sheet in sheets]
    cells = [list(hot_cells(field, 3, 3)) for field in fields]
    rows = [HotspotResponse.at_cell(sheet, field, points[0])
            for sheet, field, points in zip(sheets, fields, cells)]
    sizes = rotated_size(problem, start.rotation_deg) / 1000
    bank, upper, legal_pairs = joint_bank(problem, start, cap, meta, rows, sizes)
    costs = [move.cost for move in bank]
    common_seconds = perf_counter() - then

    def observe(location):
        b, cell = location
        response = HotspotResponse.at_cell(sheets[b], fields[b], cell)
        return response.headroom_k + cooling_bounds(bank, start, sizes, problem.power_w, response)

    def verify(i):
        source = sheets[0].power_map(bank[i].apply(start))
        gains, peaks = [], []
        for sheet, initial in zip(sheets, fields):
            final = sheet.temperatures(source)
            cell = np.unravel_index(final.argmax(), final.shape)
            gains.append(float(initial.max() - final[cell]))
            peaks.append(tuple(int(x) for x in cell))
        b = int(np.argmin(gains))
        return gains[b], (b, peaks[b])

    def best(values):
        return min(range(len(values)), key=lambda i: (-values[i], costs[i], i))

    methods = {}

    def record(name, i, estimated, checked, adjoints, since, **extra):
        methods[name] = dict(raw_best=int(i), selected=int(i) if estimated > TARGET else 0,
                             estimated_raw_k=float(estimated), candidate_fields=len(FOUR)*len(checked),
                             extra_adjoints=adjoints, checked=[int(k) for k in checked],
                             scoring_seconds=perf_counter()-since, **extra)

    now = perf_counter()
    i = best(upper)
    record("one", i, upper[i], [], 0, now)
    now = perf_counter()
    three = upper.copy()
    extras = [(b, cell) for b, points in enumerate(cells) for cell in points[1:]] if len(bank)>1 else []
    for location in extras:
        three = np.minimum(three, observe(location))
    i = best(three)
    record("three", i, three[i], [], len(extras), now)

    for name, probe in (("static_verify", None), ("adaptive", observe)):
        now = perf_counter()
        result = search_observers(upper, costs, verify, probe)
        record(name, result.best, result.best_gain_k, result.checked, len(result.observers_added), now,
               added=[dict(boundary=FOUR[b], cell_yx=cell) for b, cell in result.observers_added])

    now = perf_counter()
    truth, witnesses = [0.], [None]
    for i in range(1, len(bank)):
        score, (b, cell) = verify(i)
        truth.append(score)
        witnesses.append(dict(boundary=FOUR[b], cell_yx=cell))
    oracle = best(truth)
    record("full", oracle, truth[oracle], range(1, len(bank)), 0, now)
    assert np.all(np.asarray(truth) <= three+1e-8) and np.all(three <= upper+1e-8)
    for name in ("static_verify", "adaptive"):
        assert methods[name]["raw_best"] == oracle
    eligible = [k for k in range(len(bank)) if truth[k] > TARGET]
    reference = methods["full"]["selected"]
    for row in methods.values():
        picked = row["selected"]
        row.update(actual_gain_k=truth[picked], cost=costs[picked],
                   regret_k=truth[reference]-truth[picked],
                   raw_regret_k=truth[oracle]-truth[row["raw_best"]],
                   attained=bool(truth[picked] > TARGET))
    pool = [dict(**freeze_action(move, start, problem), old_bound_k=float(upper[k]),
                 three_bound_k=float(three[k]), full_gain_k=truth[k], worst=witnesses[k])
            for k, move in enumerate(bank)]
    cheapest = min(eligible, key=lambda k: (costs[k], k)) if eligible else None
    return dict(cap=cap, metric=meta["cost_metric"], legal_shortlist_pairs=legal_pairs,
                common_seconds=common_seconds, shared_start_fields=4, shared_old_adjoints=4,
                observers_yx=dict(zip(FOUR, cells)), methods=methods, candidates=pool,
                cheapest_passing_index=cheapest)


def constructed():
    # Three fixed sources initially. Move two equal-sized dice on a 1 mm chain.
    # Each has a single link to the stationary third die. All conductances are positive.
    n = 29
    lateral = 0.3
    sink = np.ones(n)
    sink[[7, 15]] = 3.
    sink[22:] = .25
    incidence = np.diff(np.eye(n), axis=0)
    matrix = lateral * incidence.T @ incidence + np.diag(sink)
    layouts = dict(start=(4, 11, 18), weak=(24, 26, 18), strong=(7, 15, 18))
    profiles = {}
    for name, sites in layouts.items():
        rhs = np.zeros(n)
        rhs[list(sites)] = [5., 4.95, 4.]
        profiles[name] = np.linalg.solve(matrix, rhs)
        assert abs(sink @ profiles[name] - rhs.sum()) < 1e-10
    old = profiles["start"]
    probes = [x for _, x in hot_cells(old[None, :], 3, 3)]
    result = {key:dict(sites=sites, cost_mm=sum(abs(v-sites[2]) for v in sites[:2]),
                       peak_site=int(profiles[key].argmax()), peak_k=float(profiles[key].max()),
                       three_gain_k=float(old.max()-profiles[key][probes].max()),
                       full_gain_k=float(old.max()-profiles[key].max()))
              for key, sites in layouts.items()}
    assert max(v["cost_mm"] for v in result.values()) <= result["start"]["cost_mm"]
    assert result["weak"]["three_gain_k"] > result["strong"]["three_gain_k"] > TARGET
    assert result["weak"]["full_gain_k"] < 0 < result["strong"]["full_gain_k"]
    return dict(sink_w_k=sink.tolist(), lateral_w_k=lateral, power_w=[5., 4.95, 4.],
                probe_sites=probes, layouts=result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--package-oracle", action="store_true",
                        help="During an audit, compare every frozen candidate on three diagnostic cases.")
    args = parser.parse_args()
    if args.package_oracle and not args.audit:
        parser.error("--package-oracle requires the frozen --audit selection")
    anchors = json.loads(ORIGINAL.read_bytes())["cases"]
    report = dict(anchor_sha256=text_digest(ORIGINAL), target_k=TARGET, power_fraction=.1,
                  search_boundaries={b:CENTRES[b] for b in FOUR}, cases={})
    if args.audit:
        selection = json.loads(args.audit.read_bytes())
        assert selection["anchor_sha256"] == report["anchor_sha256"]
        report["selection_sha256"] = text_digest(args.audit)
    else:
        report["counterexample"] = constructed()
    for (problem, designs, meta), anchor in zip(cases(args.cases), anchors, strict=True):
        index, start, cap = min(designs, key=lambda d: d[0])
        assert problem.name == anchor["name"] and index == anchor["anchor_id"]
        assert meta["bank_sha256"] == anchor["bank_sha256"]
        np.testing.assert_array_equal(start.centre_um, anchor["anchor_xy_um"])
        np.testing.assert_array_equal(start.rotation_deg, anchor["rotation_deg"])
        p = replace(problem, power_w=.1*problem.power_w)
        if args.audit:
            row = selection["cases"][p.name]
            if args.package_oracle:
                if p.name not in ("Case2", "Case9", "micro150"):
                    continue
                actions = {str(k):v for k,v in enumerate(row["candidates"]) if k}
                result = audit(p, start, cap, meta, dict(actions=actions), grid=64,
                               configs={b:tuple(actions) for b in FOUR})
                gains = [0.] + [min(result["conditions"][b][key]["cooling_k"] for b in FOUR) for key in actions]
                i = min(range(len(gains)), key=lambda j: (-gains[j], row["candidates"][j]["cost"], j))
                best = i if gains[i] > TARGET else 0
                picked = row["methods"]["adaptive"]["selected"]
                result.update(gains_k=gains, raw_best=i, selected=best, sheet_selected=picked,
                              package_regret_k=gains[best]-gains[picked])
            else:
                picks = {v["selected"] for v in row["methods"].values()} - {0}
                actions = {str(k):row["candidates"][k] for k in sorted(picks)}
                result = audit(p, start, cap, meta, dict(actions=actions), grid=64) if actions else dict(stayed=True)
        else:
            result = compare(p, start, cap, meta)
        report["cases"][p.name] = result
        print(p.name, flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
