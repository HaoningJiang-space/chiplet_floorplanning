"""Exact propagator controls for balanced task orders on small passive RC networks."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.linalg import expm

from periodic_layout_choice import ALTERNATE, BLOCK, DURATIONS, ORDERS, SLOTS
from chiplet_floorplanning.placement.periodic import quota_peak


def periodic_trace(steady, step, signal):
    """Directly solve the initial condition x_last=x_initial, then advance one period."""
    drive = (np.eye(len(step))-step) @ steady
    state = np.zeros(len(step))
    for mode in signal:
        state = step @ state + drive[:, mode]
    state = np.linalg.solve(np.eye(len(step))-np.linalg.matrix_power(step, len(signal)), state)
    initial = state.copy()
    trace = []
    for mode in signal:
        state = step @ state + drive[:, mode]
        trace.append(state)
    np.testing.assert_allclose(state, initial, atol=1e-9, rtol=1e-9)
    return np.asarray(trace)


def exact_orders(g, cap, powers, slot, substeps):
    steady = np.linalg.solve(g, powers)
    step = expm(-(g/cap[:, None]) * slot/substeps)
    pulse_code = np.repeat([1] + [0]*(SLOTS-1), substeps)
    pulse = periodic_trace(steady, step, pulse_code)-steady[:, 0]
    quota = quota_peak(steady[:, 0], pulse, SLOTS, SLOTS//2)
    peaks = {}
    for order in ORDERS:
        signal = np.repeat([int(c) for c in order], substeps)
        peaks[order] = float(periodic_trace(steady, step, signal).max())
    np.testing.assert_allclose(quota, max(peaks.values()), atol=1e-8, rtol=1e-9)
    return peaks


def draw(rng, index):
    n = 4 + index % 4
    edges = {(i, i+1) for i in range(n-1)}
    if index % 3 == 0:
        edges.add((0, n-1))
    elif index % 3 == 1:
        edges.update((0, i) for i in range(2, n))
    sink = 10**rng.uniform(-1.5, 1, n)
    g = np.diag(sink)
    for i,j in sorted(edges):
        v = np.eye(n)[i]-np.eye(n)[j]
        g += 10**rng.uniform(-1, 1) * np.outer(v, v)
    cap = 10**rng.uniform(-2, .8, n)
    # A common background can make a third, indirectly heated node the hottest.
    # Different spatial task maps have equal total extra watts.
    background = rng.lognormal(0, 1.3, n)
    maps = rng.dirichlet(np.full(n, .35), size=2).T
    powers = background[:, None] + 2 * maps
    return g, cap, powers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    control = exact_orders(np.eye(2), np.array([.2, .2]), np.eye(2), .05, 8)
    expected = {o: 1/(1+np.exp(-n*.05/.2)) for o, n in [(ALTERNATE, 1), (BLOCK, 4)]}
    for o in expected:
        np.testing.assert_allclose(control[o], expected[o], atol=1e-10)
    rng = np.random.default_rng(20261119)
    counts = dict(alternate=0, block=0)
    witnesses = {}
    for index in range(256):
        g, cap, powers = draw(rng, index)
        for slot in DURATIONS:
            peaks = exact_orders(g, cap, powers, slot, 8)
            losses = dict(alternate=peaks[ALTERNATE]-min(peaks.values()), block=max(peaks.values())-peaks[BLOCK])
            for key, loss in losses.items():
                counts[key] += int(loss > 1e-6)
                if key not in witnesses or loss > witnesses[key]["gap_k"]:
                    witnesses[key] = dict(index=index, slot_s=slot, gap_k=float(loss),
                                          conductance_w_k=g.tolist(), capacities_j_k=cap.tolist(),
                                          powers_w=powers.tolist(), peaks_k=peaks)
    for value in witnesses.values():
        value["refined_peaks_k"] = exact_orders(np.array(value["conductance_w_k"]), np.array(value["capacities_j_k"]),
                                                np.array(value["powers_w"]), value["slot_s"], 64)
    report = dict(control=control, analytic=expected, generated_networks=256, durations_s=DURATIONS,
                  tolerance_k=1e-6, violations=counts, witnesses=witnesses)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
