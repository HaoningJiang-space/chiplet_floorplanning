"""Construct feasible layouts for the original Case3 using interstitial memory sites."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import product
import json
from pathlib import Path

import numpy as np
from scipy.special import k0

from case3_wire_witness import BundleLengths, measure, thermal_key
from chiplet_floorplanning.placement import Layout, Problem, is_legal, pin_manhattan_um
from compare_wire_heat import digest
from wire_heat_bound import thermal_modes


def memories(cpus, signs, carrier):
    # Centres on the four sides of the CPU ring, shifted toward their owner CPU.
    for near in ([1, 3, 0, 2], [2, 0, 3, 1]):
        adjacent = cpus[near]
        for weight, inward in product((0.0, 0.15, 0.30, 0.45), (0.0, 1500.0, 3000.0)):
            mid = (cpus + adjacent) / 2
            direction = (carrier / 2 - mid) / np.maximum(
                1.0, np.linalg.norm(carrier / 2 - mid, axis=1)[:, None]
            )
            yield np.clip(
                mid + weight * (cpus - adjacent) + inward * direction,
                4500.0,
                carrier - 4500.0,
            )
    for pitch in product((9000.0, 11000.0, 13000.0, 15000.0, 17000.0), repeat=2):
        yield carrier / 2 + signs * np.array(pitch) / 2


def select(p, cert, cap):
    carrier = np.array(p.carrier_um)
    signs = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]])
    costs = BundleLengths(p)
    sigma2 = (p.size_um**2).sum(axis=1) / 12e6
    radii, weight = thermal_modes(cert)
    self_k = np.array([d["self_floor_k"] for d in cert["dies"]])
    choices = {"span": {}, "open": {}}
    counts = dict(proposed=0, legal=0, in_span=0)
    for parity in product((0, 1), repeat=4):
        size = p.size_um.copy()
        for i, z in enumerate(parity):
            if z:
                size[i] = size[i, ::-1]
        for inset in product((0.0, 1000.0, 2000.0, 3000.0, 4000.0, 6000.0), repeat=2):
            cpus = carrier / 2 + signs * (carrier / 2 - size[:4] / 2 - inset)
            for ram in memories(cpus, signs, carrier):
                counts["proposed"] += 1
                centres = np.concatenate((cpus, ram))
                layout = Layout(centres, np.array([*parity, 0, 0, 0, 0]) * 90)
                if not is_legal(p, layout, 0):
                    continue
                counts["legal"] += 1
                wire, layout = costs.best(centres, parity)
                counts["in_span"] += int(wire <= cap + 1e-9)
                key = thermal_key(centres, size, p.power_w, carrier)
                dist2 = np.sum((centres[:, None] - centres[None, :]) ** 2, axis=2) / 1e6
                rms = np.sqrt(dist2 + sigma2[:, None] + sigma2[None, :])
                mutual = k0(rms[:, :, None] / radii) @ weight
                np.fill_diagonal(mutual, 0.0)
                score = float((self_k + mutual @ p.power_w).max())
                for label, data in choices.items():
                    if label == "span" and wire > cap + 1e-9:
                        continue
                    if key not in data or wire < data[key][1]:
                        data[key] = (score, wire, layout)
    chosen = {}
    sets = {}
    for label, data in choices.items():
        ranked = sorted(data, key=lambda k: (data[k][0], data[k][1]))[:32]
        sets[label] = []
        counts[label + "_distinct"] = len(data)
        for k in ranked:
            if k not in chosen:
                chosen[k] = (len(chosen), *data[k])
            sets[label].append(chosen[k][0])
    return [v[3] for v in chosen.values()], sets, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    evidence = Path(__file__).resolve().parents[1] / "docs/evidence"
    case = args.data / "physical-calibration/atplace-import-v1/Case3.json"
    prior = next(
        c
        for c in json.loads((evidence / "global-heat-floor-v1.json").read_text())[
            "cases"
        ]
        if c["certificate"]["case"] == "Case3"
    )
    assert digest(case) == prior["certificate"]["case_sha256"]
    p = Problem.from_imported(json.loads(case.read_text()))
    cap = prior["budgets"]["span"]["cap_m"]
    layouts, groups, counts = select(p, prior["certificate"], cap)
    print("selected", counts, len(layouts), flush=True)
    old = json.loads((evidence / "wire-heat-bound-v1.json").read_text())[
        "case3_supplement"
    ]
    reference = old["fine_points"][old["chosen_index_in_fine"]]
    old_id = len(layouts)
    layouts.append(
        Layout(np.array(reference["centre_um"]), np.array(reference["rotation_deg"]))
    )
    for ids in groups.values():
        ids.append(old_id)
    run = args.data / "rs-grb-v4/case3"
    assert digest(run / "summary.json") == prior["certificate"]["summary_sha256"]
    with np.load(run / "layouts.npz") as z:
        i = int(z["length_m"].argmin())
        shortest_id = len(layouts)
        layouts.append(Layout(z["centre_um"][i], z["rotation_deg"][i]))
    points = []
    for l in layouts:
        assert is_legal(p, l, 0)
        points.append(
            dict(
                centre_um=l.centre_um.tolist(),
                rotation_deg=l.rotation_deg.tolist(),
                length_m=float(pin_manhattan_um(p, l).sum() / 1e6),
                checks={},
            )
        )
    assert all(points[j]["length_m"] <= cap + 1e-8 for j in groups["span"])
    with ProcessPoolExecutor(args.workers) as pool:
        for grid in (64, 96):
            for point, obs in zip(
                points, pool.map(measure, [(p, 0, l, grid) for l in layouts])
            ):
                point["checks"][grid] = obs
        rank = lambda i: max(v["peak_c"] for v in points[i]["checks"].values())
        fine = {name: sorted(ids, key=rank)[:4] for name, ids in groups.items()}
        ids = sorted({shortest_id, old_id, *fine["span"], *fine["open"]})
        for j, obs in zip(
            ids, pool.map(measure, [(p, 0, layouts[i], 128) for i in ids])
        ):
            points[j]["checks"][128] = obs
    for g in (64, 96, 128):
        assert (
            abs(
                reference["checks"][str(g)]["peak_c"]
                - points[old_id]["checks"][g]["peak_c"]
            )
            < 1e-6
        )
    for name in fine:
        fine[name] = sorted(set([*fine[name], old_id]))
    out = dict(
        driver_sha256=digest(Path(__file__)),
        case_sha256=digest(case),
        counts=counts,
        span_cap_m=cap,
        groups=groups,
        fine=fine,
        prior_id=old_id,
        shortest_id=shortest_id,
        points=points,
    )
    (args.output / "layouts.json").write_text(json.dumps(out, allow_nan=False) + "\n")
    for name, ids in fine.items():
        j = min(ids, key=rank)
        print(name, rank(j), points[j]["length_m"], flush=True)


if __name__ == "__main__":
    main()
