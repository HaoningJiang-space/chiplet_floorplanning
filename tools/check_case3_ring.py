"""Recheck a single all-layout temperature decision with a fixed subdivision tree."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path
import subprocess

import numpy as np
from chiplet_floorplanning.placement import Problem
from case3_ring_certificate import (
    RING,
    PAIRS,
    tables,
    modes,
    self_resistance,
    mutual_tables,
)
from compare_wire_heat import digest
from wire_heat_bound import bundle_data

STATE = {}


def check(turns):
    s = STATE
    size = np.array([[8.0, 9.0] if t % 2 == 0 else [9.0, 8.0] for t in turns])
    sep = np.array([4 * (size[i] + size[j]) for i, j in PAIRS])
    entries = [s["pins"][e, turns[i], turns[j]] for e, (i, j) in enumerate(RING)]
    blocks = (
        [s["wire"], s["self"]],
        [v[0] for v in entries],
        312 - sep,
        sep,
        [v[1] for v in entries],
        [s["kernel"][turns[i] % 2, turns[j] % 2] for i, j in PAIRS],
    )
    data = b"".join(np.asarray(block, dtype="<f8").tobytes() for block in blocks)
    proc = subprocess.run(
        [s["binary"], str(s["target"])], input=data, capture_output=True, check=True
    )
    n, g, w, h, u = map(int, proc.stdout.split())
    assert n == 2 * (g + w + h + u) - 1
    return dict(turns=turns, boxes=n, geometry=g, wire=w, thermal=h, unresolved=u)


def setup(s):
    STATE.update(s)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument(
        "--target-c",
        type=float,
        default=109.91,
        help="Peak-temperature threshold in degrees Celsius",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    src = args.data / "physical-calibration/atplace-import-v1/Case3.json"
    e = Path(__file__).resolve().parents[1] / "docs/evidence/global-heat-floor-v1.json"
    c = next(
        x
        for x in json.loads(e.read_text())["cases"]
        if x["certificate"]["case"] == "Case3"
    )
    cert = c["certificate"]
    p = Problem.from_imported(json.loads(src.read_text()))
    assert digest(src) == cert["case_sha256"]
    edges, _ = bundle_data(p, 0)
    r, w = modes(cert)
    h, _ = self_resistance(8, 9, r, w)
    cpp = Path(__file__).with_name("case3_ring_replay.cpp")
    binary = (args.output / "replay").resolve()
    subprocess.run(
        ["c++", "-std=c++17", "-O3", str(cpp), "-o", str(binary)], check=True
    )
    cap = c["budgets"]["tight"]["cap_m"]
    s = dict(
        binary=str(binary),
        target=args.target_c,
        self=150 * h,
        wire=(cap * 1000 - sum(e["n"] * e["min_mm"] for e in edges if e["b"] >= 4))
        / 704
        + 1e-7,
        kernel=mutual_tables(r, w),
        pins=tables(p),
    )
    with ProcessPoolExecutor(args.workers, initializer=setup, initargs=(s,)) as pool:
        answers = list(pool.map(check, [(0, *r) for r in product(range(4), repeat=3)]))
    out = dict(
        target_c=s["target"],
        cap_m=cap,
        case_sha256=digest(src),
        driver_sha256=digest(Path(__file__)),
        cpp_sha256=digest(cpp),
        branches=answers,
    )
    (args.output / "decision.json").write_text(json.dumps(out) + "\n")
    print(
        {
            k: sum(z[k] for z in answers)
            for k in ("boxes", "geometry", "wire", "thermal", "unresolved")
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
