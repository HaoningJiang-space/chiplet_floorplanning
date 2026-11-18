"""Certify Case3 CPU heating over continuous coordinates shared by the four original bundles."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import combinations, product
import json
from pathlib import Path
import subprocess

import mpmath as mp
import numpy as np
from scipy.special import erf, k0

from chiplet_floorplanning.placement import Layout, Problem, is_legal, pin_manhattan_um
from chiplet_floorplanning.placement.geometry import rotate
from compare_wire_heat import digest
from wire_heat_bound import bundle_data

PAIRS = list(combinations(range(4), 2))
RING = [(0, 1), (0, 2), (1, 3), (2, 3)]
STATE = {}


def modes(cert):
    """Return conservative decay lengths in mm and positive modal weights in K/W."""
    mp.mp.dps = 55
    val = lambda a: mp.mpf(str(a))
    stack = cert["stack"]
    n = len(stack)
    t = [val(s["t_m"]) for s in stack]
    k = [val(s["k"]) for s in stack]
    r = [
        t[i] / (2 * k[i])
        + val(stack[i]["contact_above_m2k_w"])
        + t[i + 1] / (2 * k[i + 1])
        for i in range(n - 1)
    ]
    r.append(1 / val(cert["h_w_m2k"]) + t[-1] / (2 * k[-1]))
    V = mp.matrix(n)
    for i, j in product(range(n), repeat=2):
        V[i, j] = mp.sqrt(t[i] * k[i] * t[j] * k[j]) * sum(r[max(i, j) :])
    eig, U = mp.eigsy(V)
    z = next(i for i, s in enumerate(stack) if s["id"] == "dies")
    return np.array([1000 * mp.sqrt(eig[i]) for i in range(n)], float) * (
        1 - 1e-8
    ), np.array([U[z, i] ** 2 / (2 * mp.pi * t[z] * k[z]) for i in range(n)], float) * (
        1 - 1e-8
    )


def self_resistance(width, height, radii, weights):
    # Positive lower sums in log t. The exponential is minimized at the right endpoint,
    # and the rectangular overlap factor at the left endpoint of each interval.
    edges = np.exp(np.linspace(-38, 5, 86001))

    def overlap(s):
        out = np.maximum(0.0, 1 - s * s / 6)
        mask = s > 0.05
        x = s[mask]
        out[mask] = np.sqrt(np.pi) * erf(x) / x + np.expm1(-x * x) / (x * x)
        return np.maximum(out - 1e-12, 0.0)

    per_mode = []
    for lam, weight in zip(radii, weights):
        scale = 2 * lam * np.sqrt(edges[:-1])
        per_mode.append(
            float(
                0.00025
                * weight
                * (
                    np.exp(-edges[1:])
                    @ (overlap(width / scale) * overlap(height / scale))
                )
            )
        )
    return float(sum(per_mode) * (1 - 1e-8)), per_mode


def mutual_tables(radii, weights):
    # The exact rectangle average is separately decreasing in |dx| and |dy|.
    # Evaluate a Jensen lower sum at the far corner for each distance box.
    d = np.arange(257) / 8
    sizes = [(8.0, 9.0), (9.0, 8.0)]
    result = {}
    for a, b in ((0, 0), (0, 1), (1, 1)):
        w, h = sizes[a]
        v, g = sizes[b]
        subs = 4
        pos = (np.arange(subs) + 0.5) / subs - 0.5
        ox, cx = np.unique(
            (pos[:, None] * w - pos[None, :] * v).ravel(), return_counts=True
        )
        oy, cy = np.unique(
            (pos[:, None] * h - pos[None, :] * g).ravel(), return_counts=True
        )
        variance = (w * w + h * h + v * v + g * g) / (12 * subs**2)
        out = np.zeros((len(d), len(d)))
        for x, mx in zip(ox, cx):
            for y, my in zip(oy, cy):
                r = np.sqrt((d[:, None] + x) ** 2 + (d[None, :] + y) ** 2 + variance)
                for lam, weight in zip(radii[-2:], weights[-2:]):
                    out += mx * my * weight * k0(r / lam)
        result[a, b] = np.maximum(out / subs**4 * (1 - 1e-8) - 1e-11, 0.0)
    result[1, 0] = result[0, 1]
    return result


def tables(p):
    """Tabulate each signed-axis cost, minimized over a left or right half-line."""
    points = np.arange(-512, 513) / 8
    ids = np.sort(p.pin_chip, axis=1)
    output = {}
    for e, (a, b) in enumerate(RING):
        match = (ids[:, 0] == a) & (ids[:, 1] == b)
        v = p.pin_offset_um[match].copy() / 1000
        rev = p.pin_chip[match, 0] != a
        v[rev] = v[rev, ::-1]
        assert len(v) == 704
        for i, j in product(range(4), repeat=2):
            off = rotate(v[:, 0], 90 * i) - rotate(v[:, 1], 90 * j)
            table = np.empty((2, 2, len(points)))
            for ax in (0, 1):
                med = np.median(off[:, ax])
                for kind, at in enumerate(
                    (np.maximum(points, med), np.minimum(points, med))
                ):
                    table[ax, kind] = abs(at[:, None] - off[:, ax]).mean(axis=1) - 1e-9
            output[e, i, j] = (off.mean(axis=0), table)
    return output


def run_one(job):
    turns, cap, limit = job
    s = STATE
    dims = np.array([[8.0, 9.0] if u % 2 == 0 else [9.0, 8.0] for u in turns])
    sep = np.array([(dims[i] + dims[j]) * 4 for i, j in PAIRS])
    maxd = 312 - sep
    data = [s["pins"][e, turns[a], turns[b]] for e, (a, b) in enumerate(RING)]
    allowance = (cap * 1000 - s["ram_min_mm"]) / 704 + 1e-7
    blocks = (
        [allowance, s["self_k"]],
        [x[0] for x in data],
        maxd,
        sep,
        [x[1] for x in data],
        [s["kernel"][turns[a] % 2, turns[b] % 2] for a, b in PAIRS],
    )
    blob = b"".join(np.asarray(v, dtype="<f8").tobytes() for v in blocks)
    proc = subprocess.run(
        [s["binary"], str(limit)], input=blob, capture_output=True, check=True
    )
    floor, expanded, open_count, leaf = map(float, proc.stdout.split())
    return dict(
        turns=turns,
        cap_m=cap,
        bound_c=floor if floor >= 0 else None,
        expanded=int(expanded),
        queue=int(open_count),
        smallest_terminal_c=leaf if leaf >= 0 else None,
    )


def setup(state):
    STATE.update(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--nodes", type=int, default=160000)
    parser.add_argument("--refine-nodes", type=int, default=1200000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.data / "physical-calibration/atplace-import-v1/Case3.json"
    run = args.data / "rs-grb-v4/case3"
    evidence = Path(__file__).resolve().parents[1] / "docs/evidence"
    prior = next(
        c
        for c in json.loads((evidence / "global-heat-floor-v1.json").read_text())[
            "cases"
        ]
        if c["certificate"]["case"] == "Case3"
    )
    cert = prior["certificate"]
    assert (
        digest(source) == cert["case_sha256"]
        and digest(run / "summary.json") == cert["summary_sha256"]
    )
    p = Problem.from_imported(json.loads(source.read_text()))
    ref = next(
        r
        for r in json.loads((evidence / "headroom-selection-v1.json").read_text())[
            "records"
        ]
        if r["case"] == "Case3"
    )
    assert (
        ref["gap_um"] == 0
        and np.all(p.power_w == [150] * 4 + [20] * 4)
        and np.all(p.size_um[:4] == [8000, 9000])
        and p.carrier_um == (39000, 39000)
    )
    with np.load(run / "layouts.npz") as z:
        index = int(z["length_m"].argmin())
        shortest = Layout(z["centre_um"][index], z["rotation_deg"][index])
        measured = float(pin_manhattan_um(p, shortest).sum() / 1e6)
        assert is_legal(p, shortest, 0) and abs(measured - z["length_m"][index]) < 1e-9
    tight = prior["budgets"]["tight"]["cap_m"]
    bundles, internal = bundle_data(p, 0)
    ram = [e for e in bundles if e["b"] >= 4]
    assert len(bundles) == 8 and len(ram) == 4 and internal == 0
    assert all(e["n"] == 1408 for e in ram)
    radii, weights = modes(cert)
    self_r, components = self_resistance(8, 9, radii, weights)
    cpp = Path(__file__).with_name("case3_ring_bound.cpp")
    binary = (args.output / "certify").resolve()
    subprocess.run(
        ["c++", "-std=c++17", "-O3", str(cpp), "-o", str(binary)], check=True
    )
    state = dict(
        binary=str(binary),
        self_k=max(cert["self_floor_k"], 150 * self_r),
        ram_min_mm=sum(e["n"] * e["min_mm"] for e in ram),
        pins=tables(p),
        kernel=mutual_tables(radii, weights),
    )
    out = dict(
        case_sha256=digest(source),
        archive_summary_sha256=digest(run / "summary.json"),
        py_sha256=digest(Path(__file__)),
        cpp_sha256=digest(cpp),
        radii_mm=radii.tolist(),
        weights_k_w=weights.tolist(),
        self_terms_k_w=components,
        self_floor_k=state["self_k"],
        ram_min_mm=state["ram_min_mm"],
        shortest=dict(
            id=index,
            length_m=measured,
            centre_um=shortest.centre_um.tolist(),
            rotation_deg=shortest.rotation_deg.tolist(),
        ),
        caps=[tight, measured],
        coarse_nodes=args.nodes,
        refine_nodes=args.refine_nodes,
        branches=[],
    )
    all_results = {}
    with ProcessPoolExecutor(
        args.workers, initializer=setup, initargs=(state,)
    ) as pool:
        jobs = [
            ((0, *t), cap, args.nodes)
            for cap in out["caps"]
            for t in product(range(4), repeat=3)
        ]
        for fut in as_completed([pool.submit(run_one, j) for j in jobs]):
            r = fut.result()
            all_results[tuple(r["turns"]), r["cap_m"]] = r
        coarse = list(all_results.values())
        out["coarse"] = coarse
        (args.output / "coarse.json").write_text(
            json.dumps(out, allow_nan=False) + "\n"
        )
        for cap in out["caps"]:
            subset = [
                r for r in coarse if r["cap_m"] == cap and r["bound_c"] is not None
            ]
            low = min(r["bound_c"] for r in subset)
            print("coarse", cap, low, flush=True)
            jobs = [
                (r["turns"], cap, args.refine_nodes)
                for r in subset
                if r["bound_c"] <= low + 2
                and r["queue"]
                and r["expanded"] == args.nodes
            ]
            for fut in as_completed([pool.submit(run_one, j) for j in jobs]):
                r = fut.result()
                prev = all_results[tuple(r["turns"]), cap]["bound_c"]
                assert r["bound_c"] is None or r["bound_c"] >= prev - 1e-7
                all_results[tuple(r["turns"]), cap] = r
    out["branches"] = list(all_results.values())
    (args.output / "certificate.json").write_text(
        json.dumps(out, allow_nan=False) + "\n"
    )
    for cap in out["caps"]:
        print(
            "final",
            cap,
            min(
                r["bound_c"]
                for r in out["branches"]
                if r["cap_m"] == cap and r["bound_c"] is not None
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
