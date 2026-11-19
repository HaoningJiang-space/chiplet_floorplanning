"""Test a phase-independent peak certificate with three unequal-share heat sources."""

import argparse
from itertools import permutations
import json
from pathlib import Path

import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import splu

from chiplet_floorplanning.placement.periodic import response_peak_bounds
from cut_traffic import EVIDENCE
from periodic_layout_choice import replay
from thermal_role_transfer import inputs


def contributions(model, order, dwell, steps):
    g, cap, _, unit, _, nodes, _, _ = model
    states = np.repeat(list(map(int, order)), steps)
    signal = np.eye(3)[states]
    weights = np.fft.rfft(signal - signal.mean(0), axis=0)
    freq = np.zeros((len(weights), *unit.shape), complex)
    for k in range(1, len(weights)):
        if np.max(abs(weights[k])) < 1e-12:
            continue
        shift = (1 - np.exp(-2j * np.pi * k / len(states))) * steps / dwell
        lu = splu((g + diags(shift * cap)).tocsc(), permc_spec="MMD_AT_PLUS_A")
        freq[k] = lu.solve(unit)
    observed, initial = [], []
    for role in range(3):
        trace = np.fft.irfft(freq * weights[:, role, None, None], n=len(states), axis=0)
        observed.append(trace[:, nodes, :])
        initial.append(trace[-1].copy())
    return observed, initial, signal.mean(0)


def check(meta, model, order, dwell=0.05, steps=4):
    g, cap, base, unit, sink, nodes, ambient, steady = model
    observed, initial, shares = contributions(model, order, dwell, steps)
    amp = meta["amplitude_w"]
    mean = steady[nodes] + ambient
    records = []
    for assign in permutations(range(unit.shape[1]), 3):
        changes = np.stack([amp * observed[r][:, :, site] for r, site in enumerate(assign)])
        np.testing.assert_allclose(changes.mean(1), 0, atol=1e-9)
        lower, upper = response_peak_bounds(mean, changes.min(1), changes.max(1))
        truth = float((mean + changes.sum(0)).max())
        local = float(mean.max())
        for r, site in enumerate(assign):
            inside = unit[nodes, site] > 1e-12
            local = max(local, float((mean[inside] + changes[r][:, inside].max(0)).max()))
        assert lower - 1e-8 <= truth <= upper + 1e-8
        records.append(
            dict(assignment=assign, peak_c=truth, local_score_c=local, lower_c=lower, upper_c=upper)
        )
    selected = min(records, key=lambda r: (r["local_score_c"], r["assignment"]))
    optimum = min(r["peak_c"] for r in records)
    assign = selected["assignment"]
    sites = unit[:, list(assign)]
    power = base[:, None] + amp * (sites - (sites @ shares)[:, None])
    assert power.min() >= -1e-10
    np.testing.assert_allclose(power.sum(0), base.sum(), rtol=0, atol=1e-7)
    state = steady + amp * sum(initial[r][:, site] for r, site in enumerate(assign))
    direct = replay(g, cap, power, sink, state, order, dwell, steps, nodes, ambient)
    assert abs(direct["direct_peak_c"] - selected["peak_c"]) < 1e-6
    bound = max(0.0, selected["upper_c"] - min(r["lower_c"] for r in records if r is not selected))
    return dict(
        **meta,
        order=order,
        substeps=steps,
        dwell_s=dwell,
        rows=records,
        selected=assign,
        self_loss_k=selected["peak_c"] - optimum,
        self_loss_bound_k=bound,
        direct=direct,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    entries = {
        r["case"]: r for r in json.loads((EVIDENCE / "layout-dominance-v1.json").read_bytes())["cases"]
    }
    trials = []
    for name in ("Case3", "Case4", "Case9"):
        for boundary in ("nominal", "two_sided"):
            meta, model = inputs(entries[name], args.cases / (name + ".json"), boundary, 32)
            trials.extend(check(meta, model, o) for o in ("0000112", "0120010"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(trials, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
