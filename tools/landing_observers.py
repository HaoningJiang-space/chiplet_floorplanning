"""Predict prospective hot cells from a landing footprint before querying its temperature."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement.common_move import HotspotResponse, cooling_bounds
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet, VERTICAL_MM2_K_W
from chiplet_floorplanning.placement.observer_search import search_observers
from chiplet_floorplanning.placement.relocation import Landing
from chiplet_floorplanning.placement.search import rotated_size
from common_relocation import CENTRES, FOUR, ORIGINAL, TARGET, audit
from power_uncertainty import cases, text_digest


def landing_cells(sheet, initial, start, move, sizes, power, *, check_patch=False):
    """Start temperatures plus local vertical rise from only the transferred footprint power."""
    chips = list(move.chips)
    scale = power[chips] / sizes[chips].prod(axis=1)
    half = sizes[chips] / 2
    old = start.centre_um[chips] / 1000 + sheet.carrier_offset
    new = np.asarray(move.destinations_um) / 1000 + sheet.carrier_offset
    targets = [[] for _ in initial]
    if check_patch:
        delta = sheet.power_map(move.apply(start)) - sheet.power_map(start)
    for lower, upper in zip(new-half, new+half):
        x0, y0 = sheet.edges.searchsorted(lower, side="right") - 1
        x1, y1 = sheet.edges.searchsorted(upper)
        ex, ey = sheet.edges[x0:x1+1], sheet.edges[y0:y1+1]
        local = np.zeros((y1-y0, x1-x0))
        for centres, sign in ((new, 1), (old, -1)):
            for lo, hi, density in zip(centres-half, centres+half, scale):
                dx = np.maximum(0., np.minimum(ex[1:], hi[0])-np.maximum(ex[:-1], lo[0]))
                dy = np.maximum(0., np.minimum(ey[1:], hi[1])-np.maximum(ey[:-1], lo[1]))
                local += sign * density * np.outer(dy, dx)
        if check_patch:
            np.testing.assert_allclose(local, delta[y0:y1, x0:x1], atol=1e-12, rtol=0)
        for b, field in enumerate(initial):
            guess = field[y0:y1, x0:x1] + VERTICAL_MM2_K_W * local
            dy, dx = np.unravel_index(guess.argmax(), guess.shape)
            targets[b].append((int(y0+dy), int(x0+dx)))
    return targets


def score(case, start, frozen):
    # Only coordinates, cost and the already available starting observer bound enter the search.
    bank = [Landing(tuple(a["indices"]), tuple(map(tuple, a["to_um"])), a["cost"], 0.)
            for a in frozen["candidates"]]
    costs = [a.cost for a in bank]
    upper = np.array([a["old_bound_k"] for a in frozen["candidates"]])
    sheets = [CooledSheet(case, np.asarray(CENTRES[b])) for b in FOUR]
    base = sheets[0].power_map(start)
    fields = [sheet.temperatures(base) for sheet in sheets]
    initial_peaks = [float(f.max()) for f in fields]
    old_cells = [tuple(np.unravel_index(f.argmax(), f.shape)) for f in fields]
    sizes = rotated_size(case, start.rotation_deg) / 1000
    now = perf_counter()
    queries = {}
    for i, move in enumerate(bank[1:], start=1):
        for b, cells in enumerate(landing_cells(sheets[0], fields, start, move, sizes, case.power_w,
                                               check_patch=i == 1)):
            for cell in set(cells):
                if cell != old_cells[b]:
                    queries.setdefault((b, cell), []).append(i)
    rows = {}

    def observer(location):
        if location not in rows:
            b, cell = location
            rows[location] = HotspotResponse.at_cell(sheets[b], fields[b], cell)
        return rows[location]

    for location, indices in queries.items():
        row = observer(location)
        subset = [bank[i] for i in indices]
        bound = row.headroom_k + cooling_bounds(subset, start, sizes, case.power_w, row)
        upper[indices] = np.minimum(upper[indices], bound)
    direct = min(range(len(bank)), key=lambda i: (-upper[i], costs[i], i))
    direct_time = perf_counter()-now

    def verify(i):
        source = sheets[0].power_map(bank[i].apply(start))
        final = [sheet.temperatures(source) for sheet in sheets]
        gains = [peak-f.max() for peak, f in zip(initial_peaks, final)]
        b = int(np.argmin(gains))
        cell = tuple(int(v) for v in np.unravel_index(final[b].argmax(), final[b].shape))
        return float(gains[b]), (b, cell)

    def learn(location):
        row = observer(location)
        return row.headroom_k + cooling_bounds(bank, start, sizes, case.power_w, row)

    verified = search_observers(upper, costs, verify, learn)
    combined_time = perf_counter()-now
    # Read the independent exhaustive scores only AFTER both decisions have been made.
    truth = [a["full_gain_k"] for a in frozen["candidates"]]
    reference = frozen["methods"]["full"]
    assert np.all(np.asarray(truth) <= upper+1e-8)
    assert verified.best == reference["raw_best"]
    summary = {}
    for method, raw, gain, count, field_count, elapsed in (
        ("landing", direct, upper[direct], len(queries), 0, direct_time),
        ("landing_verify", verified.best, verified.best_gain_k, len(rows), 4*len(verified.checked), combined_time)
    ):
        picked = raw if gain > TARGET else 0
        summary[method] = dict(raw_best=raw, selected=picked, estimated_raw_k=float(gain),
                               actual_gain_k=truth[picked], regret_k=truth[reference["selected"]]-truth[picked],
                               raw_regret_k=truth[reference["raw_best"]]-truth[raw], cost=costs[picked],
                               extra_adjoints=count, candidate_fields=field_count, scoring_seconds=elapsed)
    return dict(methods=summary, upper_k=upper.tolist(), checked=verified.checked,
                observers_added=[(FOUR[b], cell) for b, cell in verified.observers_added],
                distinct_landing_adjoints=len(queries), requested_landing_cells=sum(map(len, queries.values())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", required=True, type=Path)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    frozen = json.loads(args.bank.read_bytes())
    assert frozen["anchor_sha256"] == text_digest(ORIGINAL)
    report = dict(bank_sha256=text_digest(args.bank), cases={})
    if args.audit:
        predictions = json.loads(args.audit.read_bytes())
        assert predictions["bank_sha256"] == report["bank_sha256"]
        report["prediction_sha256"] = text_digest(args.audit)
    anchors = json.loads(ORIGINAL.read_bytes())["cases"]
    for (p, designs, meta), anchor in zip(cases(args.cases), anchors, strict=True):
        index, start, cap = min(designs, key=lambda d: d[0])
        assert p.name == anchor["name"] and index == anchor["anchor_id"] and meta["bank_sha256"] == anchor["bank_sha256"]
        np.testing.assert_array_equal(start.centre_um, anchor["anchor_xy_um"])
        np.testing.assert_array_equal(start.rotation_deg, anchor["rotation_deg"])
        p = replace(p, power_w=p.power_w*frozen["power_fraction"])
        case = frozen["cases"][p.name]
        assert abs(case["cap"]-cap) < 1e-9
        if args.audit:
            covered = {v["selected"] for v in case["methods"].values()} | {0}
            picked = predictions["cases"][p.name]["methods"]["landing"]["selected"]
            result = dict(already_covered=True, index=picked) if picked in covered else audit(
                p, start, cap, meta, dict(actions={str(picked):case["candidates"][picked]}), grid=64)
        else:
            result = score(p, start, case)
        report["cases"][p.name] = result
        print(p.name, flush=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
