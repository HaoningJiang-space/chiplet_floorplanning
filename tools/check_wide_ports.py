"""Check every budget-admissible choice of wide CPU port sides on the frozen Case3 placements."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path

import numpy as np

from case3_phy_experiment import EVIDENCE, inputs
from case3_phy_geometry import (
    CAP_M,
    RING,
    NEIGHBOURS,
    PROFILES,
    STATES,
    REACH_MM,
    BundleLengths,
    direct_check,
    edge_matrices,
    sizes_mm,
    memory_states,
)
from case3_phy_thermal import solve_field, thermal_limits, setup, utilisation
from compare_wire_heat import digest

CHOICES = np.array(list(product(range(len(STATES)), repeat=4)))
SIDES = STATES[CHOICES]
# Distinguish unordered bank locations on each of four CPUs; direction only affects wiring.
SIDE_KEY = (
    np.minimum(SIDES[:, :, 0], SIDES[:, :, 1]) * 4
    + np.maximum(SIDES[:, :, 0], SIDES[:, :, 1])
) @ (16 ** np.arange(4))
WORK = {}


def init(p):
    WORK.update(p=p, costs=BundleLengths(p))


def alternatives(row, cap=CAP_M):
    p = WORK["p"]
    profile = PROFILES["wide"]
    xy = np.array(row["centres_um"]) / 1000
    size = sizes_mm(p, row["parity"])
    mem, turns = memory_states(xy, row["parity"], WORK["costs"])
    ram = mem[np.arange(4), CHOICES].sum(axis=1)
    length = ram.copy()
    maximum = np.zeros(len(length))
    for a, b in RING:
        cost, worst = edge_matrices(
            tuple(size[a]), tuple(size[b]), xy[b] - xy[a], profile
        )
        ai = SIDES[:, a, NEIGHBOURS[a].index(b)]
        bj = SIDES[:, b, NEIGHBOURS[b].index(a)]
        length += cost[ai, bj]
        maximum = np.maximum(maximum, worst[ai, bj])
    within = maximum <= REACH_MM + 1e-10
    minimum = float(np.min(length[within], initial=np.inf))
    assert abs(minimum - row["profiles"]["wide"]["wire_m"]) < 1e-8
    ids = np.flatnonzero(within & (length <= cap + 1e-10))
    ordered = ids[np.argsort(length[ids], kind="stable")]
    _, first = np.unique(SIDE_KEY[ordered], return_index=True)
    configs = []
    for k in ordered[first]:
        rotation = (90 * turns[np.arange(4), CHOICES[k]].T.ravel()).tolist()
        configs.append(
            dict(
                wire_m=float(length[k]),
                memory_m=float(ram[k]),
                sides=SIDES[k].tolist(),
                rotation_deg=rotation,
                max_cpu_signal_mm=float(maximum[k]),
                latency_ns=4.125 + float(maximum[k]) / 150,
            )
        )
    return len(ids), configs


def check(row):
    p = WORK["p"]
    count, configs = alternatives(row)
    low = 1e3
    cold = None
    positive = []
    base_peaks = []
    for c in configs:
        variant = dict(row, profiles={"wide": c})
        field, _, err = solve_field(p, variant, "wide", 64, 0.0)
        assert abs(err) < 1e-7
        t = float(np.nanmax(field))
        base_peaks.append(t)
        if t < low:
            low = t
            cold = c
        if t <= 109:
            setup(p, [variant])
            checks = {
                g: thermal_limits((row["id"], "wide", g))[-1] for g in (64, 96, 128)
            }
            positive.append(
                dict(config=c, checks=checks, utilisation=utilisation(checks, 0.25))
            )
    if cold:
        direct_check(p, np.array(row["centres_um"]), cold, PROFILES["wide"])
    return dict(
        id=row["id"],
        ordered=count,
        thermal_signatures=len(configs),
        minimum_base_c=low,
        cold=cold,
        base_peaks_c=base_peaks,
        under_109=positive,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("data", "first", "output"):
        parser.add_argument("--" + option, required=True, type=Path)
    parser.add_argument("--workers", default=16, type=int)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("use a fresh file")
    manifest = json.loads((EVIDENCE / "case3-phy-population-v1.json").read_text())
    pop = args.first / "population.json"
    geom = args.first / "geometry.json"
    original = json.loads((EVIDENCE / "case3-phy-codesign-v1.json").read_text())
    assert (
        digest(pop) == manifest["raw_sha256"]["population.json"]
        and digest(geom) == original["raw_sha256"]["geometry.json"]
    )
    eligible = {
        r["id"] for r in json.loads(pop.read_text())["checks"] if r["profile"] == "wide"
    }
    rows = [r for r in json.loads(geom.read_text())["rows"] if r["id"] in eligible]
    assert {r["id"] for r in rows} == eligible
    p, _, _ = inputs(args.data)
    with ProcessPoolExecutor(args.workers, initializer=init, initargs=(p,)) as pool:
        checked = list(pool.map(check, rows, chunksize=1))
    out = dict(
        driver_sha256=digest(Path(__file__)),
        input_population_sha256=digest(pop),
        geometries=len(rows),
        rows=checked,
        ordered=sum(r["ordered"] for r in checked),
        thermal_signatures=sum(r["thermal_signatures"] for r in checked),
    )
    args.output.write_text(json.dumps(out, allow_nan=False) + "\n")
    print(
        "finished",
        out["ordered"],
        out["thermal_signatures"],
        min(r["minimum_base_c"] for r in checked),
        flush=True,
    )


if __name__ == "__main__":
    main()
