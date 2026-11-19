"""Check shared link and thermal admissibility over mixtures of directed MPI workloads."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations_with_replacement
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Problem
from cut_traffic import EVIDENCE, digest
from mixed_phy import bank_thermal_field
from module_capacity import GRIDS, profile
from shared_capacity import NAMES, TARGET, mapped_traffic, physical_capacity

WEIGHTS = np.vstack(
    [
        [
            np.bincount(v, minlength=8) / 4
            for v in combinations_with_replacement(range(8), 4)
        ],
        np.full(8, 1 / 8),
    ]
)
assert WEIGHTS.shape == (331, 8)


def link_trial(job):
    modules, target, normalized, loads = job
    cap = np.asarray(modules) * 256
    demand8 = np.concatenate([normalized, normalized.transpose(0, 2, 1)])
    flow8 = np.concatenate([loads, loads[:, :, ::-1]])
    observed_peak = flow8.max(axis=(0, 2))
    assert np.all(observed_peak <= cap + 1e-7)
    mixed = np.tensordot(WEIGHTS, demand8, axes=1)
    # Optimize routes from each mixed endpoint demand directly, independently of the
    # known feasible load certificate obtained by combining the original routings.
    index = int(np.ravel_multi_index(modules, (5,) * 4))
    service = np.array(physical_capacity((index, mixed)))
    assert min(service) >= target - 1e-8
    carried = np.tensordot(WEIGHTS, flow8, axes=1)
    assert np.max(carried - cap[None, :, None]) < 1e-7
    assert np.allclose(carried.max(axis=(0, 2)), observed_peak)
    # Directed load transposition swaps TX/RX but preserves each model bank's watts.
    watts = (0.25 * cap + 0.75 * carried.mean(axis=2)) / 1000
    endpoint_w = (0.25 * cap + 0.75 * flow8.mean(axis=2)) / 1000
    assert np.max(abs(watts - WEIGHTS @ endpoint_w)) < 1e-10
    return dict(
        modules=modules,
        target_TB_s=target,
        profiles=len(WEIGHTS),
        minimum_optimized_service_TB_s=float(service.min()),
        minimum_over_terminal_profiles_TB_s=float(
            service[(WEIGHTS == 1).any(axis=1)].min()
        ),
        max_capacity_excess_gbps=max(0, float(np.max(carried - cap[None, :, None]))),
    )


def field_trial(job):
    p, row, selection, grid = job
    shapes = [profile(m) for m in selection["modules"]]

    def field(watts):
        return bank_thermal_field(
            p, row, row["actual_config"], grid, shapes, watts, node_limit=450000
        )

    watts = np.array([selection["modes"][k]["endpoint_w"] for k in NAMES])
    fields = []
    edge_ref = None
    peaks = []
    for name, w in zip(NAMES, watts):
        obs, f, axes = field(w)
        if edge_ref is None:
            edge_ref = axes
        assert all(np.array_equal(a, b) for a, b in zip(axes, edge_ref))
        assert (
            abs(
                obs["peak_power_layer_c"]
                - selection["modes"][name]["grids"][str(grid)]["peak_c"]
            )
            < 1e-6
        )
        fields.append(f)
        peaks.append(obs["peak_power_layer_c"])
    rows = []
    for weights in (np.full(8, 1 / 8), np.array([4, 2, 1, 1, 0, 0, 0, 0]) / 8):
        combined = weights[:4] + weights[4:]
        obs, f, axes = field(combined @ watts)
        assert all(np.array_equal(a, b) for a, b in zip(axes, edge_ref))
        predicted = np.tensordot(combined, fields, axes=1)
        assert np.array_equal(np.isfinite(f), np.isfinite(predicted))
        error = float(np.nanmax(abs(f - predicted)))
        assert error < 1e-6 and obs["peak_power_layer_c"] <= max(peaks) + 1e-6
        rows.append(
            dict(
                weights=weights.tolist(),
                direct_peak_c=obs["peak_power_layer_c"],
                max_cell_error_k=error,
                balance_error_w=abs(obs["energy_balance_error_w"]),
            )
        )
    return dict(
        grid=grid,
        active_power_layer_cells=int(np.isfinite(fields[0]).sum()),
        terminal_peak_c=peaks,
        mixed_fields=rows,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ("data", "payload", "shared", "output"):
        ap.add_argument("--" + k, type=Path, required=True)
    args = ap.parse_args()
    prior = json.loads((EVIDENCE / "shared-capacity-v1.json").read_text())
    assert (
        digest(args.shared) == prior["raw_sha256"]["shared.json"]
        and digest(args.payload) == prior["raw_sha256"]["capture/payload.json"]
    )
    src = args.data / "physical-calibration/atplace-import-v1/Case3.json"
    assert (
        digest(src)
        == json.loads((EVIDENCE / "capacity-cost-v1.json").read_text())[
            "physical_model"
        ]["raw_source_sha256"]
    )
    p = Problem.from_imported(json.loads(src.read_text()))
    demand, _ = mapped_traffic(
        json.loads(args.payload.read_text()), np.arange(16) % 4, 4
    )
    layouts = json.loads(args.shared.read_text())["physical"]["layout_trials"]
    configurations = {}
    for r in layouts:
        for c in r["cases"]:
            for method in ("sized", "uniform"):
                v = c[method]
                if v is None:
                    continue
                key = tuple(v["modules"]), c["target_TB_s"]
                loads = np.array([v["modes"][k]["directed_raw_gbps"] for k in NAMES])
                if key in configurations:
                    assert np.allclose(loads, configurations[key][3])
                else:
                    configurations[key] = (*key, demand, loads)
    row = json.loads((EVIDENCE / "case3-selective-rate-v1.json").read_text())[
        "threshold_witnesses"
    ][0]
    layout = next(r for r in layouts if r["layout"] == row["id"])
    selection = next(c["sized"] for c in layout["cases"] if c["target_TB_s"] == TARGET)
    with ProcessPoolExecutor(5) as pool:
        links = list(pool.map(link_trial, configurations.values()))
        controls = list(pool.map(field_trial, [(p, row, selection, g) for g in GRIDS]))
    with args.output.open("x") as f:
        json.dump(
            dict(
                driver_sha256=digest(Path(__file__)),
                thermal_sha256=digest(Path(__file__).with_name("mixed_phy.py")),
                shared_sha256=digest(args.shared),
                link_trials=links,
                thermal_layout=row["id"],
                thermal_modules=selection["modules"],
                thermal_target_TB_s=TARGET,
                original_demand_order=list(NAMES),
                thermal_checks=controls,
            ),
            f,
            allow_nan=False,
        )


if __name__ == "__main__":
    main()
