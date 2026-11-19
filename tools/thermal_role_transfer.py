"""Test equal-watt thermal roles across site types, cooling boundaries, and task times."""

import argparse
from dataclasses import replace
from itertools import combinations
import json
from pathlib import Path

import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import splu

from chiplet_floorplanning.package import checked_solution
from chiplet_floorplanning.placement import Layout, Problem, is_legal
from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.thermal import thermal_case_data
from cut_traffic import EVIDENCE, digest
from periodic_layout_choice import package_model, replay


CASES = [1, 3, 4, 6, 7, 8, 9, 10]
BOUNDARIES = ["nominal", "half_top", "two_sided"]
DWELLS = [0.005, 0.05, 0.5]


def candidate_sites(p):
    types = {}
    for i, name in enumerate(p.names):
        kind = name.rsplit("_", 1)[0]
        if kind.startswith(("CPU", "GPU")):
            types.setdefault(kind, []).append(i)
    ordered = sorted(types.values(), key=lambda ids: (p.power_w[ids[0]], ids[0]))
    if not ordered:
        raise ValueError("no CPU or GPU sites are available for the site-role comparison")
    return ordered[0][:4] if len(ordered) == 1 else ordered[0][:2] + ordered[-1][:2]


def inputs(entry, source, boundary, grid, *, geometry=None, fixed_sites=None):
    assert digest(source) == entry["input_sha256"]
    p = Problem.from_imported(json.loads(source.read_bytes()))
    r = (
        geometry
        if geometry is not None
        else min(entry["layouts"], key=lambda x: (x["length_m"], x["layout"]))
    )
    layout = Layout(np.array(r["centre_um"]), np.array(r["rotation_deg"]))
    length = float(pin_manhattan_um(p, layout).sum() / 1e6)
    assert is_legal(p, layout, 0) and length <= entry["length_cap_m"] and abs(length - r["length_m"]) < 1e-8
    sites = candidate_sites(p) if fixed_sites is None else fixed_sites
    mean = 0.25 * p.power_w
    mean[sites] = 0.6 * p.power_w[sites]
    amplitude = 0.4 * min(p.power_w[sites])
    maps = [mean, *(mean + np.eye(len(mean))[i] for i in sites)]
    data = [thermal_case_data(replace(p, power_w=w), layout, 0, grid) for w in maps]
    for case in data:
        thermal = case["thermal"]
        if boundary == "half_top":
            thermal["top_h_w_m2k"] *= 0.5
        elif boundary == "two_sided":
            thermal["bottom_h_w_m2k"] = thermal["top_h_w_m2k"]
    g, capacity, sources, sink, nodes, ambient = package_model(data)
    baseline = sources[:, 0]
    unit = sources[:, 1:] - baseline[:, None]
    np.testing.assert_allclose(unit.sum(axis=0), np.ones(len(sites)), atol=1e-9, rtol=0)
    assert unit.min() >= -1e-12
    steady = splu(g.tocsc(), permc_spec="MMD_AT_PLUS_A").solve(baseline)
    checked_solution(g, baseline, sink, steady)
    meta = dict(
        case=entry["case"],
        boundary=boundary,
        grid=grid,
        anchor=r["layout"],
        length_m=length,
        budget_m=entry["length_cap_m"],
        site_names=[p.names[i] for i in sites],
        rated_power_w=p.power_w[sites].tolist(),
        footprint_mm2=(p.size_um[sites].prod(1) / 1e6).tolist(),
        mean_total_w=float(mean.sum()),
        amplitude_w=amplitude,
        top_h_w_m2k=thermal["top_h_w_m2k"],
        bottom_h_w_m2k=thermal["bottom_h_w_m2k"],
    )
    return meta, (g, capacity, baseline, unit, sink, nodes, ambient, steady)


def alternating_fields(g, cap, unit, dwell, steps):
    """Phase-end response per watt at all nodes for each independent square-wave source."""
    samples = 2 * steps
    spectrum = np.fft.rfft(np.repeat([1.0, -1.0], steps))
    coeff = np.zeros((len(spectrum), *unit.shape), dtype=complex)
    for k in range(1, len(spectrum), 2):
        omega = 2 * np.pi * k / samples
        admittance = g + diags((1 - np.exp(-1j * omega)) * cap * steps / dwell)
        lu = splu(admittance.tocsc(), permc_spec="MMD_AT_PLUS_A")
        coeff[k] = spectrum[k] * lu.solve(unit)
    return np.fft.irfft(coeff, n=samples, axis=0)


def magnitude_bounds(mean, first, second):
    """Cycle peak bounds for opposite half-wave-symmetric drives.

    first and second are the nonnegative single-source swing amplitudes (K)
    at every observed location. Their time phases need not be known.
    """
    return float(np.max(mean + abs(first - second))), float(np.max(mean + first + second))


def compare(meta, model, dwell, steps, *, replay_all=False):
    g, cap, baseline, unit, sink, nodes, ambient, steady = model
    full = alternating_fields(g, cap, unit, dwell, steps)
    response = full[:, nodes, :]
    np.testing.assert_allclose(response[:steps], -response[steps:], atol=1e-9, rtol=0)
    mean = steady[nodes] + ambient
    masks = unit[nodes].T > 1e-12
    amp = meta["amplitude_w"]
    magnitudes = amp * np.abs(response).max(0)
    site_c = [float(mean[m].max()) for m in masks]
    self_c = [float((mean[m] + amp * np.abs(response[:, m, i]).max(0)).max()) for i, m in enumerate(masks)]
    rows = []
    for i, j in combinations(range(len(masks)), 2):
        swing = amp * np.abs(response[:, :, i] - response[:, :, j]).max(0)
        peak = float((mean + swing).max())
        lower, upper = magnitude_bounds(mean, magnitudes[:, i], magnitudes[:, j])
        assert lower - 1e-8 <= peak <= upper + 1e-8
        rows.append(
            dict(
                pair=[i, j],
                mean_score_c=max(site_c[i], site_c[j]),
                self_score_c=float(max(mean.max(), self_c[i], self_c[j])),
                peak_c=peak,
                lower_c=lower,
                upper_c=upper,
            )
        )

    def select(key):
        return min(rows, key=lambda r: (r[key], r["pair"]))

    best, old, new = (select(key) for key in ("peak_c", "mean_score_c", "self_score_c"))
    loss_bound = max(
        0.0,
        new["upper_c"]
        - min((row["lower_c"] for row in rows if row["pair"] != new["pair"]), default=np.inf),
    )
    for row in rows if replay_all else [old]:
        i, j = row["pair"]
        delta = amp * (unit[:, i] - unit[:, j])
        power = np.column_stack((baseline + delta, baseline - delta))
        assert power.min() >= -1e-10
        np.testing.assert_allclose(power.sum(axis=0), meta["mean_total_w"], atol=1e-7, rtol=0)
        initial = steady + amp * (full[-1, :, i] - full[-1, :, j])
        direct = replay(g, cap, power, sink, initial, "01", dwell, steps, nodes, ambient)
        assert abs(direct["direct_peak_c"] - row["peak_c"]) < 1e-6
        if row is old:
            old_direct = direct
        if replay_all:
            row["direct"] = direct
    return dict(
        **meta,
        dwell_s=dwell,
        substeps=steps,
        peaks=rows,
        steady_peak_c=float(mean.max()),
        site_mean_c=site_c,
        site_self_peak_c=self_c,
        mean_pair=old["pair"],
        self_pair=new["pair"],
        best_pair=best["pair"],
        mean_loss_k=old["peak_c"] - best["peak_c"],
        self_loss_k=new["peak_c"] - best["peak_c"],
        self_loss_bound_k=loss_bound,
        range_k=max(r["peak_c"] for r in rows) - best["peak_c"],
        direct=old_direct,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--refine", type=Path, help="replay the largest losses of both rules in this screen")
    args = ap.parse_args()
    entries = {
        r["case"]: r for r in json.loads((EVIDENCE / "layout-dominance-v1.json").read_bytes())["cases"]
    }
    conditions = [(f"Case{n}", b, DWELLS) for n in CASES for b in BOUNDARIES]
    grid, steps = 32, 4
    if args.refine:
        screened = json.loads(args.refine.read_bytes())["rows"]
        selected = [max(screened, key=lambda r: r[metric]) for metric in ("mean_loss_k", "self_loss_k")]
        conditions = [
            (c, b, [d])
            for c, b, d in dict.fromkeys((r["case"], r["boundary"], r["dwell_s"]) for r in selected)
        ]
        grid, steps = 64, 8
    results = []
    for name, boundary, dwells in conditions:
        meta, model = inputs(entries[name], args.cases / (name + ".json"), boundary, grid)
        results.extend(compare(meta, model, dwell, steps) for dwell in dwells)
        print(name, boundary, flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dict(rows=results), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
