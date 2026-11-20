"""Choose joint landings with a conserved-power reference field and compare cold-start costs."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement.common_move import HotspotResponse, cooling_bounds
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet, LATERAL_W_K, VERTICAL_MM2_K_W
from chiplet_floorplanning.placement.observer_search import search_observers
from chiplet_floorplanning.placement.relocation import Landing
from chiplet_floorplanning.placement.search import rotated_size
from chiplet_floorplanning.placement.transfer_bound import (
    ContactPlane, InsulatedSheet, ThermalMargin, joint_peak, moved_watts, path_upper_k,
)
from common_relocation import CENTRES, FOUR, ORIGINAL, TARGET, audit, freeze_action
from observer_placement import joint_bank
from power_uncertainty import cases, text_digest


PRIOR = ORIGINAL.parents[1] / "observer-placement"
METHODS = ("full", "feedback", "guaranteed", "transfer", "lazy_transfer", "plane_guaranteed",
           "plane_verified", "singles", "singles_whole")
EPS = 1e-8


def starting_cases(source):
    anchors = json.loads(ORIGINAL.read_bytes())["cases"]
    for (p, designs, meta), anchor in zip(cases(source), anchors, strict=True):
        index, start, cap = min(designs, key=lambda d: d[0])
        assert (p.name, index, meta["bank_sha256"]) == (anchor["name"], anchor["anchor_id"], anchor["bank_sha256"])
        np.testing.assert_array_equal(start.centre_um, anchor["anchor_xy_um"])
        np.testing.assert_array_equal(start.rotation_deg, anchor["rotation_deg"])
        yield replace(p, power_w=p.power_w*.1), start, cap, meta


class JointSelection:
    def __init__(self, p, start, cap, meta):
        self.sheets = [CooledSheet(p, np.asarray(CENTRES[b])) for b in FOUR]
        self.base = self.sheets[0].power_map(start)
        self.fields = [sh.temperatures(self.base) for sh in self.sheets]
        self.peaks = [float(f.max()) for f in self.fields]
        self.sizes = rotated_size(p, start.rotation_deg)/1000
        self.p, self.start = p, start
        rows = [HotspotResponse.at_cell(sh, f, np.unravel_index(f.argmax(), f.shape))
                for sh, f in zip(self.sheets, self.fields)]
        self.bank, self.old_upper, _ = joint_bank(p, start, cap, meta, rows, self.sizes)
        self.costs = [s.cost for s in self.bank]
        self.forwards = self.adjoints = self.references = 0
        self.single_fields = self.cache_bytes = self.visited_cells = self.eligible_cells = 0
        self.joint_checks = self.tiebreak = 0

    def setup_reference(self, plane=False):
        self.reference = InsulatedSheet(self.base.shape, LATERAL_W_K, VERTICAL_MM2_K_W)
        self.margins = [ThermalMargin(field, sh.sink) for field, sh in zip(self.fields, self.sheets)]
        self.planes = [ContactPlane(sh) if plane else None for sh in self.sheets]

    def windows(self, action):
        delta = moved_watts(self.sheets[0], self.start, action, self.sizes, self.p.power_w)
        ref = self.reference.transfer(delta)
        self.references += 1
        # Includes every final powered cell, even if old and new fractional
        # rectangles cancel to roundoff. Additional old cells are safe to keep.
        exposed = (self.base > 0) | (delta > 0)
        return [margin.window(ref, exposed, plane) for margin, plane in zip(self.margins, self.planes)]

    def verify(self, i, windows=None):
        watts = self.sheets[0].power_map(self.bank[i].apply(self.start))
        order = range(len(FOUR)) if windows is None else sorted(range(len(FOUR)), key=lambda b: windows[b].gain_low_k)
        worst, witness = np.inf, None
        for b in order:
            if windows is not None and windows[b].gain_low_k > worst + EPS:
                break
            field = self.sheets[b].temperatures(watts)
            self.forwards += 1
            cell = np.unravel_index(field.argmax(), field.shape)
            gain = float(self.peaks[b]-field[cell])
            if gain < worst or (gain == worst and b < witness[0]):
                worst, witness = gain, (b, cell)
        return worst, witness

    def observe(self, witness):
        b, cell = witness
        row = HotspotResponse.at_cell(self.sheets[b], self.fields[b], cell)
        self.adjoints += 1
        return row.headroom_k + cooling_bounds(self.bank, self.start, self.sizes, self.p.power_w, row)

    def best(self, values):
        return min(range(len(values)), key=lambda i: (-values[i], self.costs[i], i))

    def single(self, cache, chip, dest):
        key = chip, dest
        if key not in cache:
            move = Landing((chip,), (dest,), 0., 0.)
            q = moved_watts(self.sheets[0], self.start, move, self.sizes, self.p.power_w)
            fields = [sh.temperatures(q) for sh in self.sheets]
            added = q > 0
            maxima = [max(0., float(f[added].max())) if added.any() else 0. for f in fields]
            cache[key] = fields, maxima, added
            self.single_fields += len(fields)
            self.cache_bytes += added.nbytes + sum(f.nbytes for f in fields)
        return cache[key]

    def cached_choice(self, *, use_margin):
        cache = {}
        gains = {0:0.}
        hot = [int(f.argmax()) for f in self.fields]
        def evaluate(i):
            move = self.bank[i]
            responses = [self.single(cache, chip, dest) for chip, dest in zip(move.chips, move.destinations_um, strict=True)]
            if use_margin:
                possible = self.base > 0
                for _, _, added in responses:
                    possible |= added
                eligible = int(possible.sum())
            self.joint_checks += 1
            worst, witness = np.inf, None
            for b, initial in enumerate(self.fields):
                changes = [fs[b] for fs, _, _ in responses]
                if use_margin:
                    bound = sum(mx[b] for _, mx, _ in responses)
                    peak, cell, count = joint_peak(initial, hot[b], changes, bound, possible)
                else:
                    combined = initial.copy()
                    for change in changes:
                        combined += change
                    cell = np.unravel_index(combined.argmax(), combined.shape)
                    peak, count, eligible = float(combined[cell]), combined.size, combined.size
                self.visited_cells += count
                self.eligible_cells += eligible
                gain = self.peaks[b]-peak
                if gain < worst:
                    worst, witness = gain, (b, cell)
            gains[i] = worst
            return worst, witness

        result = search_observers(self.old_upper, self.costs, evaluate, self.observe)
        near = [i for i, g in gains.items() if g >= result.best_gain_k-EPS]
        if len(near) > 1 or abs(result.best_gain_k-TARGET) < EPS:
            # Preserve the baseline's floating-point tie order for indistinguishable heatmaps.
            for i in near:
                if i:
                    gains[i] = self.verify(i)[0]
                    self.tiebreak += 1
            best = min(near, key=lambda i: (-gains[i], self.costs[i], i))
            return best, gains[best]
        return result.best, result.best_gain_k

    def choose(self, method):
        if method in ("singles", "singles_whole"):
            return self.cached_choice(use_margin=method == "singles")
        if method == "full":
            values = [0.] + [self.verify(i)[0] for i in range(1, len(self.bank))]
            i = self.best(values)
            return i, values[i]
        if method == "feedback":
            result = search_observers(self.old_upper, self.costs, self.verify, self.observe)
            return result.best, result.best_gain_k

        self.setup_reference(plane=method.startswith("plane_"))
        windows = {}
        if method in ("lazy_transfer", "plane_verified"):
            def tighten(i):
                ranges = self.windows(self.bank[i])
                windows[i] = ranges
                return min(w.gain_high_k for w in ranges)
            result = search_observers(self.old_upper, self.costs, lambda i: self.verify(i, windows[i]),
                                      self.observe, tighten=tighten)
            return result.best, result.best_gain_k
        upper = self.old_upper.copy()
        lower = np.full(len(self.bank), -np.inf)
        lower[0] = 0.
        for i, move in enumerate(self.bank[1:], 1):
            if upper[i] < -EPS:
                continue
            ranges = self.windows(move)
            windows[i] = ranges
            lower[i] = min(w.gain_low_k for w in ranges)
            upper[i] = min(upper[i], min(w.gain_high_k for w in ranges))
        direct = self.best(lower)
        if method in ("guaranteed", "plane_guaranteed"):
            return direct, float(lower[direct])
        upper[upper < lower[direct]-EPS] = -np.inf
        result = search_observers(upper, self.costs, lambda i: self.verify(i, windows[i]), self.observe)
        return result.best, result.best_gain_k


def run_method(source, method):
    begin = perf_counter()
    decisions = {}
    previous = begin
    for p, start, cap, meta in starting_cases(source):
        selector = JointSelection(p, start, cap, meta)
        ready = perf_counter()
        raw, score = selector.choose(method)
        picked = raw if score > TARGET else 0
        finish = perf_counter()
        decisions[p.name] = dict(raw=raw, selected=picked, decision_gain_k=score,
            action=freeze_action(selector.bank[picked], start, p),
            cap=cap, metric=meta["cost_metric"], candidates=len(selector.bank)-1,
            forwards=selector.forwards, adjoints=selector.adjoints, references=selector.references,
            calibration_rhs=2*len(FOUR) if method.startswith("plane_") else 0,
            single_fields=selector.single_fields, cache_bytes=selector.cache_bytes,
            joint_checks=selector.joint_checks, tie_checks=selector.tiebreak,
            visited_cells=selector.visited_cells, eligible_cells=selector.eligible_cells,
            prepare_s=ready-previous, score_s=finish-ready)
        previous = finish
    return dict(total_s=perf_counter()-begin, cases=decisions)


def timing(source, repeats):
    records = {m:[] for m in METHODS}
    for t in range(repeats):
        offset = (2*t) % len(METHODS)
        for method in METHODS[offset:] + METHODS[:offset]:
            record = run_method(source, method)
            records[method].append(record)
            print(t+1, method, round(record["total_s"], 3), flush=True)
    return dict(protocol="371c35c", repetitions=repeats, powers_fraction=.1,
                bank_sha256=text_digest(PRIOR/"selection.json"), runs=records)


def archived_move(a):
    return Landing(tuple(a["indices"]), tuple(map(tuple, a["to_um"])), a["cost"], 0.)


def group_stats(rows):
    names = ("exact_rise_k", "rise_bound_k", "unknown_bound_k", "over_k", "plane_bound_k", "plane_width_k",
             "single_bound_k", "single_excluded_fraction", "joint_peak_error_k",
             "path_bound_k", "path_excluded_fraction", "gain_width_k", "unknown_width_k",
             "excluded_fraction", "plane_excluded_fraction", "ideal_excluded_fraction")
    detail = {k:dict(zip(("min", "median", "max"), map(float,np.quantile([r[k] for r in rows],[0,.5,1]))))
              for k in names}
    return dict(fields=len(rows), mean_shortcut_understates_rise=int(sum(r["mean_error_k"] > EPS for r in rows)),
                **detail)


def two_node_control():
    # One watt moves between two fixed sites. Scaling every conductance leaves
    # geometry, transferred power and connectivity unchanged.
    q = np.array([-1., 1.])
    matrix = np.array([[5., -1.], [-1., 1.25]])
    examples = {str(scale):np.linalg.solve(scale*matrix, q).tolist() for scale in (1., .1, .01)}
    assert np.isclose(examples["1.0"][1], 16/21) and examples["0.01"][1] > 76.
    return dict(q_w=q.tolist(), unit_edge_w_k=1., unit_shunts_w_k=[4., .25],
                no_contact_reference_k=[-.5,.5], mean_offset_prediction_k=.5,
                rise_by_conductance_scale=examples)


def compare_fields(obj, action, unknown, cache):
    delta = moved_watts(obj.sheets[0], obj.start, action, obj.sizes, obj.p.power_w)
    watts = obj.sheets[0].power_map(action.apply(obj.start))
    np.testing.assert_allclose(watts-obj.base, delta, atol=1e-10, rtol=0)
    transfer = obj.reference.transfer(delta)
    path_bound = path_upper_k(obj.start, action, obj.sizes, obj.p.power_w, LATERAL_W_K, VERTICAL_MM2_K_W)
    singles = [obj.single(cache, chip, dest) for chip, dest in zip(action.chips, action.destinations_um, strict=True)]
    active = watts > 0
    exposed = (obj.base>0) | (delta>0)
    rows = []
    for b, sh in enumerate(obj.sheets):
        final = sh.temperatures(watts)
        old = obj.fields[b]
        rise = max(0.,float((final-old).max()))
        assert rise <= path_bound+EPS
        gain = float(obj.peaks[b]-final.max())
        single_bound = sum(mx[b] for _, mx, _ in singles)
        peak, _, _ = joint_peak(old, int(old.argmax()), [fs[b] for fs, _, _ in singles], single_bound, exposed)
        peak_error = abs(peak-float(final.max()))
        assert rise <= single_bound+EPS and peak_error < EPS
        known = obj.margins[b].window(transfer, exposed)
        loose = unknown[b].window(transfer, exposed)
        improved = obj.margins[b].window(transfer, exposed, obj.planes[b])
        for w in (known, loose, improved):
            if rise > w.rise_upper_k+EPS or not w.gain_low_k-EPS <= gain <= w.gain_high_k+EPS:
                raise AssertionError((obj.p.name, b, rise, gain, w))
        target = obj.peaks[b]-TARGET
        safe = old + known.rise_upper_k < target-EPS
        assert np.all(final[safe] < target)
        avg = transfer.bare_k.ravel()[sh.sink>0].mean()
        highest = float(transfer.source_surface_k.ravel()[transfer.added].max()) if transfer.added.size else 0.
        rows.append(dict(exact_rise_k=rise, rise_bound_k=known.rise_upper_k, unknown_bound_k=loose.rise_upper_k,
                    single_bound_k=single_bound, single_excluded_fraction=float((old[active]+single_bound < target-EPS).mean()),
                    joint_peak_error_k=peak_error,
                    plane_bound_k=improved.rise_upper_k, plane_width_k=improved.gain_high_k-improved.gain_low_k,
                    plane_excluded_fraction=float((old[active]+improved.rise_upper_k < target-EPS).mean()),
                    path_bound_k=path_bound, path_excluded_fraction=float((old[active]+path_bound < target-EPS).mean()),
                    over_k=known.rise_upper_k-rise, gain_width_k=known.gain_high_k-known.gain_low_k,
                    unknown_width_k=loose.gain_high_k-loose.gain_low_k, excluded_fraction=float(safe[active].mean()),
                    ideal_excluded_fraction=float((old[active]+rise < target-EPS).mean()),
                    mean_error_k=rise-max(0., highest-avg), gain_k=gain,
                    gain_low_k=known.gain_low_k, gain_high_k=known.gain_high_k))
    return rows


def audit_run(source, times_path):
    times = json.loads(times_path.read_bytes())
    archive = json.loads((PRIOR/"selection.json").read_bytes())
    extra = json.loads((PRIOR/"challenge-moves.json").read_bytes())
    assert times["bank_sha256"] == text_digest(PRIOR/"selection.json") == extra["bank_sha256"]
    out = dict(timing_sha256=text_digest(times_path), bank_sha256=times["bank_sha256"], cases={})
    out["two_node"] = two_node_control()
    package_oracle_path = PRIOR/"package-oracle.json"
    prior_package = json.loads(package_oracle_path.read_bytes())
    assert prior_package["selection_sha256"] == times["bank_sha256"]
    out["prior_package_oracle_sha256"] = text_digest(package_oracle_path)
    all_main, all_extra = [], []
    for p,start,cap,meta in starting_cases(source):
        obj = JointSelection(p, start, cap, meta)
        obj.setup_reference(plane=True)
        unknown = [ThermalMargin(f, np.ones(f.shape,bool)) for f in obj.fields]
        old = archive["cases"][p.name]
        main = []
        singles = {}
        for move, a in zip(obj.bank, old["candidates"], strict=True):
            assert move.chips == tuple(a["indices"]) and abs(move.cost-a["cost"]) < 1e-9
            np.testing.assert_array_equal(move.destinations_um, a["to_um"])
            if move.chips:
                rows = compare_fields(obj, move, unknown, singles)
                assert abs(min(r["gain_k"] for r in rows)-a["full_gain_k"]) < EPS
                main.append(rows)
                all_main.extend(rows)
        challenge = [r for a in extra["cases"][p.name] for r in compare_fields(obj, archived_move(a), unknown, singles)]
        all_extra.extend(challenge)
        # Independent whole-board peak ranking. Include the unchanged placement.
        scores = [0.] + [min(r["gain_k"] for r in group) for group in main]
        oracle = obj.best(scores)
        chosen = oracle if scores[oracle] > TARGET else 0
        eligible = [i for i, score in enumerate(scores) if score > TARGET]
        shortest = min(eligible, key=lambda i: (obj.costs[i], i)) if eligible else None
        result = dict(oracle_raw=oracle, oracle_chosen=chosen, shortest_passing=shortest,
                      shortest_cost=obj.costs[shortest] if eligible else None,
                      bounds=[dict(full_k=min(r["gain_k"] for r in group),
                                   lower_k=min(r["gain_low_k"] for r in group),
                                   upper_k=min(r["gain_high_k"] for r in group)) for group in main],
                      methods={})
        for arm, runs in times["runs"].items():
            v = runs[0]["cases"][p.name]
            i = v["selected"]
            np.testing.assert_array_equal(obj.bank[i].destinations_um, v["action"]["to_um"])
            assert obj.bank[i].chips == tuple(v["action"]["indices"])
            assert all((t["cases"][p.name]["raw"], t["cases"][p.name]["selected"]) ==
                       (v["raw"], i) for t in runs)
            if arm not in ("guaranteed", "plane_guaranteed"):
                assert v["raw"] == oracle and i == chosen and abs(v["decision_gain_k"]-scores[oracle]) < EPS
            else:
                assert v["decision_gain_k"] <= scores[v["raw"]]+EPS
            result["methods"][arm] = dict(raw=v["raw"], selected=i, gain_k=scores[i], cost=obj.costs[i],
                                          regret_k=scores[chosen]-scores[i], raw_regret_k=scores[oracle]-scores[v["raw"]])
        picks = sorted({row["selected"] for row in result["methods"].values()} - {0})
        actions = {str(i):freeze_action(obj.bank[i], start, p) for i in picks}
        tested = audit(p, start, cap, meta, dict(actions=actions), grid=64) if picks else None
        package = {"0":dict(four_k=0., centre_k=0.)}
        for i in picks:
            by_contact = {b:row[str(i)]["cooling_k"] for b, row in tested["conditions"].items()}
            package[str(i)] = dict(four_k=min(by_contact[b] for b in FOUR), centre_k=by_contact["centre"],
                                   by_contact_k=by_contact)
        if p.name in prior_package["cases"]:
            checked = prior_package["cases"][p.name]
            for i in picks:
                assert abs(package[str(i)]["four_k"]-checked["gains_k"][i]) <= EPS
            result["package_oracle_selected"] = checked["selected"]
            result["package_oracle_k"] = checked["gains_k"][checked["selected"]]
        result["package_selected"] = package
        out["cases"][p.name] = result
    out.update(main=group_stats(all_main), holdout=group_stats(all_extra))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--audit", type=Path)
    args = ap.parse_args()
    report = audit_run(args.cases, args.audit) if args.audit else timing(args.cases, args.repeat)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
