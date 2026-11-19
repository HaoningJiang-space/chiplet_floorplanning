"""Counterexamples to mean-only and independent self-heating site selection."""

import argparse
from itertools import combinations
import json
from pathlib import Path

import numpy as np
from scipy.linalg import expm
from scipy.optimize import brentq
from thermal_role_transfer import magnitude_bounds


def continuous_trace(g, cap, mean, delta, dwell, samples=128):
    """Exact continuous half-step propagator; solve closure then sample both half cycles."""
    m = -(g / cap[:, None])
    half = expm(m * dwell)
    fixed_offset = np.linalg.solve(g, delta)
    start = -np.linalg.solve(np.eye(len(g)) + half, (np.eye(len(g)) - half) @ fixed_offset)
    dt = expm(m * (dwell / samples))
    state = start.copy()
    trace = []
    for target in (fixed_offset, -fixed_offset):
        for _ in range(samples):
            state = target + dt @ (state - target)
            trace.append(mean + state)
    np.testing.assert_allclose(state, start, atol=1e-11)
    np.testing.assert_allclose(np.mean(trace, axis=0), mean, atol=1e-11)
    return np.array(trace)


def storage():
    cap = np.array([0.025, 0.25, 0.5])
    sink = np.array([1.0, 1.0, 10.0])
    mean = np.array([5.0, 5.3, 0.3])
    rows = []
    for mutual in (0.0, 0.02):
        g = np.diag(sink) + mutual * (3 * np.eye(3) - np.ones((3, 3)))
        base = g @ mean
        for dwell in (0.005, 0.05, 0.5, 2.0):
            peaks = []
            for i in (0, 1):
                delta = np.eye(3)[i] - np.eye(3)[2]
                assert (base - np.abs(delta) >= 0).all() and delta.sum() == 0
                peak = float(continuous_trace(g, cap, mean, delta, dwell).max())
                if mutual == 0:
                    amplitude = abs(delta) / sink * np.tanh(dwell * sink / (2 * cap))
                    np.testing.assert_allclose((mean + amplitude).max(), peak, atol=1e-11)
                peaks.append(peak)
            rows.append(
                dict(
                    mutual_w_k=mutual,
                    dwell_s=dwell,
                    peak_rise_k=peaks,
                    best_site=int(np.argmin(peaks)),
                    total_w=float(base.sum()),
                )
            )

    def crossing(dwell):
        return np.tanh(dwell / (2 * cap[0])) - np.tanh(dwell / (2 * cap[1])) - (mean[1] - mean[0])

    return dict(
        mean_rise_k=mean.tolist(),
        cap_j_k=cap.tolist(),
        sink_w_k=sink.tolist(),
        rows=rows,
        uncoupled_crossings_s=[brentq(crossing, 0.005, 0.05), brentq(crossing, 0.05, 0.5)],
    )


def mutual_heating():
    cap = np.full(4, 0.05)
    sink = np.array([0.5, 0.5, 1.4, 1.4])
    mean = np.full(4, 5.0)
    g = np.diag(sink)
    for i, j in combinations(range(4), 2):
        link = np.eye(4)[i] - np.eye(4)[j]
        conductance = 4.0 if (i, j) == (0, 1) else (0.0 if (i, j) == (2, 3) else 0.02)
        g += conductance * np.outer(link, link)
    dwell = 0.5
    single = np.array([continuous_trace(g, cap, mean, src, dwell) - mean for src in np.eye(4)])
    self_scores = [float(mean[i] + abs(single[i, :, i]).max()) for i in range(4)]
    rows = []
    for i, j in combinations(range(4), 2):
        delta = np.eye(4)[i] - np.eye(4)[j]
        assert ((g @ mean) - abs(delta) > 0).all()
        peak = float(continuous_trace(g, cap, mean, delta, dwell).max())
        paired = float((mean + np.abs(single[i] - single[j]).max(0)).max())
        lower, upper = magnitude_bounds(mean, abs(single[i]).max(0), abs(single[j]).max(0))
        assert lower - 1e-9 <= peak <= upper + 1e-9
        np.testing.assert_allclose(paired, peak, atol=1e-11)
        if (i, j) in ((0, 1), (2, 3)):
            # Antiphase excitation of two symmetric sites is a single eigenmode.
            modal_g = (g @ delta)[i]
            np.testing.assert_allclose(
                peak, mean[i] + np.tanh(dwell * modal_g / (2 * cap[i])) / modal_g, atol=1e-11
            )
        rows.append(
            dict(
                pair=[i, j],
                self_score_k=max(self_scores[i], self_scores[j]),
                peak_rise_k=peak,
                lower_k=lower,
                upper_k=upper,
            )
        )
    self_choice = min(rows, key=lambda r: r["self_score_k"])
    optimum = min(rows, key=lambda r: r["peak_rise_k"])
    return dict(
        g_w_k=g.tolist(),
        cap_j_k=cap.tolist(),
        mean_rise_k=mean.tolist(),
        dwell_s=dwell,
        pairs=rows,
        self_choice=self_choice["pair"],
        best=optimum["pair"],
        self_loss_k=self_choice["peak_rise_k"] - optimum["peak_rise_k"],
        self_loss_bound_k=max(
            0.0, self_choice["upper_k"] - min(r["lower_k"] for r in rows if r != self_choice)
        ),
    )


def draw_storage(data, path):
    import matplotlib.pyplot as plt

    times = np.geomspace(0.001, 2, 600)
    mean = np.array(data["mean_rise_k"])
    c = np.array(data["cap_j_k"])
    peaks = [np.maximum(mean[i] + np.tanh(times / (2 * c[i])), mean[1 - i]) for i in (0, 1)]
    fig, ax = plt.subplots(figsize=(7.4, 3.6), layout="constrained")
    ax.plot(
        times * 1000, peaks[0], label="Assign pulse to cooler-mean site (5.0 K)", color="#ad502c", lw=2.3
    )
    ax.plot(
        times * 1000, peaks[1], label="Assign pulse to warmer-mean site (5.3 K)", color="#196988", lw=2.3
    )
    a, b = np.array(data["uncoupled_crossings_s"]) * 1000
    ax.axvspan(a, b, color="#dad7cd", alpha=0.5)
    for t in (a, b):
        ax.axvline(t, lw=0.8, color="#78756e", ls="--")
    ax.set(
        xscale="log",
        xlabel="Time per task (ms)",
        ylabel="Peak rise over ambient (K)",
        title="The preferred site changes twice as the task gets longer",
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=9)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--figure", type=Path)
    args = parser.parse_args()
    dest = args.output
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = dict(storage=storage(), mutual=mutual_heating())
    dest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.figure:
        draw_storage(result["storage"], args.figure)
