"""Find a three-grid full-rate witness with the most geometric detour allowance among tested ports."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from itertools import product
from pathlib import Path

import numpy as np

from case3_phy_experiment import EVIDENCE, inputs
from case3_phy_geometry import (
    CAP_M,
    REACH_MM,
    PROFILES,
    RING,
    STATES,
    NEIGHBOURS,
    bank,
    sizes_mm,
    memory_states,
    select_ports,
    direct_check,
    BundleLengths,
)
from case3_phy_thermal import setup, thermal_limits
from check_case3_phy_population import fourfold
from chiplet_floorplanning.placement.geometry import rotate
from compare_wire_heat import digest


def stretch(config):
    return min(
        CAP_M / config["wire_m"],
        REACH_MM / config["max_cpu_signal_mm"],
        (5.0 - 2.0 - 272 * 8 / 1024) * 150 / config["max_cpu_signal_mm"],
    )


def brute_wire(p, row, name):
    """Directly enumerate all 12^4 ordered side choices using individual original/synthesized pins."""
    profile = PROFILES[name]
    xy = np.array(row["centres_um"]) / 1000
    size = sizes_mm(p, row["parity"])
    states = np.array(list(product(range(len(STATES)), repeat=4)))
    cost = np.zeros(len(states))
    ids = np.sort(p.pin_chip, axis=1)
    for i in range(4):
        nets = (ids[:, 0] == i) & (ids[:, 1] == i + 4)
        offsets = p.pin_offset_um[nets] / 1000
        reverse = p.pin_chip[nets, 0] != i
        offsets[reverse] = offsets[reverse, ::-1]
        options = np.full(len(STATES), np.inf)
        for turn in [row["parity"][i], row["parity"][i] + 2]:
            left = xy[i] + rotate(offsets[:, 0], 90 * turn)
            best = min(
                abs(left - xy[i + 4] - rotate(offsets[:, 1], 90 * t)).sum() / 1000
                for t in range(4)
            )
            valid = (STATES != turn).all(axis=1)
            options[valid] = np.minimum(options[valid], best)
        cost += options[states[:, i]]
    for i, j in RING:
        table = np.zeros((4, 4))
        for a, b in product(range(4), repeat=2):
            lpad = xy[i] + bank(tuple(size[i]), a, profile)[0]
            rpad = xy[j] + bank(tuple(size[j]), b, profile)[0]
            lengths = abs(lpad - rpad).sum(axis=1)
            table[a, b] = (
                lengths.sum() / 1000 if lengths.max() <= 25 + 1e-10 else np.inf
            )
        ai = STATES[states[:, i], NEIGHBOURS[i].index(j)]
        bj = STATES[states[:, j], NEIGHBOURS[j].index(i)]
        cost += table[ai, bj]
    expected = row["profiles"][name]["wire_m"]
    assert abs(float(cost.min()) - expected) < 1e-8
    return float(cost.min())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("data", "first", "population", "output"):
        parser.add_argument("--" + arg, required=True, type=Path)
    parser.add_argument("--workers", default=14, type=int)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a fresh output file")
    p, _, _ = inputs(args.data)
    original = json.loads((args.first / "geometry.json").read_text())["rows"]
    pop = json.loads(args.population.read_text())
    extra, _, _ = fourfold(p, original)
    rows = {r["id"]: r for r in original + extra}
    candidates = [
        x
        for x in pop["checks"]
        if x["profile"] == "narrow"
        and x["checks"]["64"]["power_fraction"] >= 1.0 - 1e-12
    ]
    bundles = BundleLengths(p)
    eligible = {}
    for item in candidates:
        i = item["id"]
        row = rows[i]
        if "profiles" not in row:
            xy = np.array(row["centres_um"]) / 1000
            size = sizes_mm(p, row["parity"])
            m, t = memory_states(xy, row["parity"], bundles)
            row["profiles"] = {
                n: select_ports(xy, size, m, t, prof) for n, prof in PROFILES.items()
            }
        eligible[i] = item
    ranked = sorted(
        eligible, key=lambda i: (-stretch(rows[i]["profiles"]["narrow"]), i)
    )
    winner = None
    inspected = 0
    with ProcessPoolExecutor(
        args.workers, initializer=setup, initargs=(p, [rows[i] for i in ranked])
    ) as pool:
        for start in range(0, len(ranked), 14):
            batch = ranked[start : start + 14]
            all_checks = {i: dict(eligible[i]["checks"]) for i in batch}
            jobs = [
                (i, "narrow", g)
                for i in batch
                for g in (96, 128)
                if str(g) not in all_checks[i]
            ]
            for i, _, g, v in pool.map(thermal_limits, jobs):
                all_checks[i][str(g)] = v
            for i in batch:
                inspected += 1
                if (
                    min(x["power_fraction"] for x in all_checks[i].values())
                    >= 1.0 - 1e-12
                ):
                    winner = i
                    checks = all_checks[i]
                    break
            if winner is not None:
                break
    assert winner is not None
    row = rows[winner]
    audit = {}
    for name, config in row["profiles"].items():
        if config:
            direct_check(p, np.array(row["centres_um"]), config, PROFILES[name])
            audit[name] = brute_wire(p, row, name)
    prior = json.loads((EVIDENCE / "case3-ring-certificate-v1.json").read_text())
    memory_floor = prior["heat_lower_bound"]["reserved_dram_bundle_sum_mm"] / 1000
    bounds = {}
    for i in {winner, pop["results"]["union"]["narrow"]["best_id"]}:
        xy = np.array(rows[i]["centres_um"]) / 1000
        permitted_sums = []
        for parity in product((0, 1), repeat=4):
            size = sizes_mm(p, parity)
            gaps = [
                float(
                    np.maximum(abs(xy[a] - xy[b]) - (size[a] + size[b]) / 2, 0.0).sum()
                )
                for a, b in RING
            ]
            permitted_sums.append(sum(gaps))
        # A necessary memory bound at these centres; relax all CPU/DRAM rotations independently.
        exact_memory_relaxation = 0.0
        for j in range(4):
            dx, dy = (xy[j + 4] - xy[j]) * 1000
            exact_memory_relaxation += (
                min(
                    bundles.length(j, j + 4, a, b, dx, dy)
                    for a, b in product(range(4), repeat=2)
                )
                / 1e6
            )
        bound_gap = min(permitted_sums)
        bounds[i] = dict(
            min_summed_cpu_gaps_over_all_orientations_mm=bound_gap,
            unconditional_memory_floor_m=memory_floor,
            fixed_centres_memory_floor_m=exact_memory_relaxation - 1e-8,
            wide_floor_m=memory_floor + 0.352 * bound_gap,
            wide_fixed_centres_floor_m=exact_memory_relaxation
            - 1e-8
            + 0.352 * bound_gap,
        )
    out = dict(
        driver_sha256=digest(Path(__file__)),
        population_sha256=digest(args.population),
        eligible_64_full=len(ranked),
        checked_in_priority_order=inspected,
        winner_id=winner,
        centres_um=row["centres_um"],
        configs=row["profiles"],
        checks=checks,
        length_stretch=stretch(row["profiles"]["narrow"]),
        brute_min_m=audit,
        bounds=bounds,
    )
    args.output.write_text(json.dumps(out, allow_nan=False) + "\n")
    print("margin", winner, out["length_stretch"], flush=True)


if __name__ == "__main__":
    main()
