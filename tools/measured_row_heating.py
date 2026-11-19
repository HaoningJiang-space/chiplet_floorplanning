"""Predict simultaneous-row TTC heating from two separate physical step records."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import socket
import tarfile

import numpy as np


ARCHIVE_SHA256 = "3fc86c8d59a3b1cff1f45d1caa7eb21e56be39e22d75f24fb6ba2557b92111b0"
SAMPLE_HZ = 10
SECONDS = 20
NAMES = ("line_1", "line_2", "thickline_1")


def read_step(raw, active_rows):
    a = np.loadtxt(io.BytesIO(raw))
    assert a.ndim == 2 and a.shape[1] == 49 and np.isfinite(a).all()
    power = a[:, :16] * a[:, 16:32]
    temperature = a[:, 32:48]
    # Archive protocol: 0.2 W idle per cell, 3 W active; use midpoint for
    # event detection only. Use actual measured V*I for the power comparison.
    threshold = 16 * 0.2 + 4 * active_rows * (3 - 0.2) / 2
    edges = np.diff(np.r_[False, power.sum(axis=1) > threshold, False].astype(int))
    starts, stops = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    i = np.argmax(stops - starts)
    begin, end = int(starts[i]), int(stops[i])
    assert begin >= SAMPLE_HZ and end - begin >= SAMPLE_HZ * SECONDS
    before = slice(begin - SAMPLE_HZ, begin)
    during = slice(begin, begin + SAMPLE_HZ * SECONDS)
    growth = temperature[during] - temperature[before].mean(axis=0)
    additional = power[during] - power[before].mean(axis=0)
    meta = dict(
        sha256=hashlib.sha256(raw).hexdigest(),
        start_sample=begin,
        active_samples=end - begin,
        baseline_total_w=float(power[before].sum(axis=1).mean()),
        baseline_mean_c=float(temperature[before].mean()),
    )
    return additional, growth, meta


def measure(archive, group):
    sources = {}
    steps = []
    for name, rows in zip(NAMES, (1, 1, 2)):
        with archive.extractfile(f"release/{group}/{name}.csv") as f:
            power, rise, sources[name] = read_step(f.read(), rows)
            steps.append((power, rise))
    predicted_power = steps[0][0] + steps[1][0]
    predicted_rise = steps[0][1] + steps[1][1]
    actual_power, actual_rise = steps[2]
    error = predicted_rise - actual_rise
    max_at = np.unravel_index(np.abs(error).argmax(), error.shape)
    summary = dict(
        group=group,
        sources=sources,
        sample_hz=SAMPLE_HZ,
        window_s=SECONDS,
        sensor_samples=error.size,
        measured_peak_rise_k=float(actual_rise.max()),
        predicted_peak_rise_k=float(predicted_rise.max()),
        rmse_k=float(np.sqrt(np.mean(error**2))),
        mean_error_k=float(error.mean()),
        max_abs_error_k=float(np.abs(error).max()),
        max_error_sensor_1_based=int(max_at[1]) + 1,
        max_error_sample_0_based=int(max_at[0]),
        measured_mean_increment_total_w=float(actual_power.sum(axis=1).mean()),
        predicted_mean_increment_total_w=float(predicted_power.sum(axis=1).mean()),
        mean_power_map_discrepancy_relative_l2=float(
            np.linalg.norm((predicted_power - actual_power).mean(axis=0))
            / np.linalg.norm(actual_power.mean(axis=0))
        ),
        per_sensor_rmse_k=np.sqrt(np.mean(error**2, axis=0)).tolist(),
    )

    return summary, actual_rise, predicted_rise


def plot_runs(runs, output):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(
        2,
        2,
        figsize=(8.6, 5.3),
        sharex=True,
        sharey="row",
        gridspec_kw={"height_ratios": [2, 1]},
        layout="constrained",
    )
    for col, (summary, actual, predicted) in enumerate(runs):
        seconds = np.arange(len(actual)) / SAMPLE_HZ
        top, bottom = axes[:, col]
        top.set_title(
            ["Natural convection", "Fan cooling"][col], loc="left", fontweight="bold"
        )
        top.plot(
            seconds,
            actual.max(axis=1),
            color="#164968",
            label="Measured, both rows",
            lw=2.1,
        )
        top.plot(
            seconds,
            predicted.max(axis=1),
            color="#c75524",
            label="Sum of single-row rises",
            linestyle="--",
            lw=1.8,
        )
        error = predicted - actual
        bottom.fill_between(
            seconds,
            error.min(axis=1),
            error.max(axis=1),
            color="#dbe8ec",
            label="Range across 16 sensors",
        )
        bottom.axhline(0, lw=0.8, color="#777777")
        bottom.plot(
            seconds, error.mean(axis=1), color="#164968", lw=1.15, label="Mean error"
        )
        bottom.set_xlabel("Time from detected power step (s)")
        bottom.set_title(f"RMSE {summary['rmse_k']:.3f} K", loc="left", fontsize=10)
        for ax in (top, bottom):
            ax.spines[["right", "top"]].set_visible(False)
            ax.grid(axis="y", alpha=0.18)
            ax.set_xlim(0, SECONDS)
    axes[0, 0].set_ylabel("Highest sensor rise (K)")
    axes[1, 0].set_ylabel("Prediction error (K)")
    axes[0, 0].legend(loc="lower right", frameon=False, fontsize=8)
    axes[1, 1].legend(loc="upper right", frameon=False, fontsize=8)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--figure", type=Path, help="optional physical trace comparison plot"
    )
    args = parser.parse_args()
    assert hashlib.sha256(args.archive.read_bytes()).hexdigest() == ARCHIVE_SHA256
    with tarfile.open(args.archive, "r:gz") as archive:
        runs = [measure(archive, group) for group in ("heatsink", "heatsink_with_fan")]
    result = dict(
        source="Terraneo, Leva & Fornaciari, SAMOS 2019, Zenodo 3345878 v2 (CC BY)",
        archive_sha256=ARCHIVE_SHA256,
        protocol_commit="035cabbc47925fadc84721fe37e238447040fa68",
        host=socket.gethostname(),
        driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        groups=[run[0] for run in runs],
    )
    if args.figure:
        plot_runs(runs, args.figure)
    with args.output.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")


if __name__ == "__main__":
    main()
