"""E1: independent source heating, rigid translations and boundary sensitivity."""

import argparse
import copy
import hashlib
import itertools
import json
import platform
from pathlib import Path
from time import perf_counter

import numpy as np
import scipy

from chiplet_floorplanning.layout import relocate_design
from chiplet_floorplanning.model import load_case, parse_case
from chiplet_floorplanning.thermal_decomposition import decompose_sources
from validation.factorial import factorial_decomposition
from validation.sources import git_revision, write_json


PROFILES = {
    "nominal": (1000, 0, 10),
    "weaker_top": (500, 0, 10),
    "stronger_top": (2000, 0, 10),
    "bottom_only": (0, 1000, 10),
    "lower_tim_k": (1000, 0, 1),
    "higher_tim_k": (1000, 0, 20),
}


def plot_contributions(samples, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    fig, axes = plt.subplots(2, 3, figsize=(12, 6), layout="constrained")
    for col, field in enumerate(("total", "tx", "rx")):
        maximum = max(float(np.nanmax(grids[field])) for _, _, grids in samples)
        for row, (name, case, grids) in enumerate(samples):
            ax = axes[row, col]
            artist = ax.pcolormesh(
                case.mesh.x_edges_mm,
                case.mesh.y_edges_mm,
                grids[field],
                shading="flat",
                vmin=0,
                vmax=maximum,
                cmap="inferno",
                rasterized=True,
            )
            for die in case.dies:
                rect = die.bounds
                ax.add_patch(
                    Rectangle(
                        (rect.x, rect.y),
                        rect.width,
                        rect.height,
                        fill=False,
                        edgecolor="tab:blue",
                        linewidth=0.8,
                    )
                )
            ax.set(
                title=f"{name}: {field} temperature rise",
                xlabel="Package x (mm)",
                ylabel="Package y (mm)",
            )
            ax.set_aspect("equal")
        fig.colorbar(artist, ax=axes[:, col], label="Temperature rise (K)", shrink=0.8)
    fig.suptitle(
        "Same materials; only heat sources change. Power-layer cell values; blank = no die material."
    )
    fig.savefig(output / "source_contributions.svg")
    fig.savefig(output / "source_contributions.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = perf_counter()
    repo = Path(__file__).resolve().parents[1]
    base = load_case(repo / "examples/low_speed_gpio.json")
    coordinates = list(itertools.product((0.5, 1.5, 2.5), (6, 7, 8), (1, 2, 3)))
    profiles, samples = {}, []
    for profile, (top, bottom, tim_k) in PROFILES.items():
        raw = copy.deepcopy(base.input_data)
        raw["thermal"].update(top_h_w_m2k=top, bottom_h_w_m2k=bottom)
        next(l for l in raw["thermal"]["layers"] if l["id"] == "tim")[
            "conductivity_w_mk"
        ] = tim_k
        raw["thermal"]["provenance"] += (
            " E1 profile: "
            + profile
            + "; declared sensitivity assumption, not calibration."
        )
        design = parse_case(raw)
        rows = []
        for index, (tx, rx, y) in enumerate(coordinates):
            name = f"layout_{index:02d}"
            folder = args.output / profile / name
            folder.mkdir(parents=True)
            placement = dict(tx=dict(x=tx, y=y), rx=dict(x=rx, y=2))
            meshes = []
            resolutions = [(48, 32), (96, 64)]
            if profile == "bottom_only":
                resolutions.append((192, 128))
            for nx, ny in resolutions:
                case = relocate_design(
                    design,
                    placement,
                    grid=dict(nx=nx, ny=ny, mode="geometry_conformal"),
                )
                decomposition, grids = decompose_sources(case)
                meshes.append(
                    dict(
                        requested_grid_nx_ny=[nx, ny],
                        nx=case.nx,
                        ny=case.ny,
                        **decomposition,
                    )
                )
                np.savez_compressed(
                    folder / f"source_rises_{nx}x{ny}.npz",
                    **grids,
                    x_edges_mm=case.mesh.x_edges_mm,
                    y_edges_mm=case.mesh.y_edges_mm,
                )
            write_json(folder / "case.json", case.input_data)
            np.savez_compressed(
                folder / "source_rises.npz",
                **grids,
                x_edges_mm=case.mesh.x_edges_mm,
                y_edges_mm=case.mesh.y_edges_mm,
            )
            peak_change = abs(
                meshes[-1]["total_hotspot"]["temperature_c"]
                - meshes[-2]["total_hotspot"]["temperature_c"]
            )
            row = dict(
                id=name,
                placement_mm=placement,
                meshes=meshes,
                peak_c=meshes[-1]["total_hotspot"]["temperature_c"],
                hotspot=meshes[-1]["total_hotspot"],
                mesh_peak_change_k=peak_change,
                initial_peak_grid_change_k=abs(
                    meshes[1]["total_hotspot"]["temperature_c"]
                    - meshes[0]["total_hotspot"]["temperature_c"]
                ),
                source_contribution_change_at_each_mesh_hotspot_k={
                    n: abs(
                        meshes[-1]["total_hotspot"]["source_contributions_k"][n]
                        - meshes[-2]["total_hotspot"]["source_contributions_k"][n]
                    )
                    for n in ("tx", "rx")
                },
            )
            rows.append(row)
            write_json(folder / "report.json", row)
            if profile == "nominal" and index in (0, 24):
                samples.append((name, case, grids))
        factor_coordinates = [(x, y, rx) for x, rx, y in coordinates]
        factors = {
            "total_peak_rise": factorial_decomposition(
                factor_coordinates,
                [r["hotspot"]["total_rise_k"] for r in rows],
                ("tx_x", "tx_y", "rx_x"),
            )
        }
        for source in ("tx", "rx"):
            factors[source + "_at_total_hotspot"] = factorial_decomposition(
                factor_coordinates,
                [r["hotspot"]["source_contributions_k"][source] for r in rows],
                ("tx_x", "tx_y", "rx_x"),
            )
        coldest = min(rows, key=lambda r: r["peak_c"])
        profiles[profile] = dict(
            parameters=dict(
                top_h_w_m2k=top, bottom_h_w_m2k=bottom, tim_conductivity_w_mk=tim_k
            ),
            candidates=rows,
            factorial=factors,
            coldest_id=coldest["id"],
            candidates_not_separated_from_raw_min_by_mesh_change=[
                r["id"]
                for r in rows
                if r["peak_c"] - coldest["peak_c"]
                <= r["mesh_peak_change_k"] + coldest["mesh_peak_change_k"]
            ],
            minimum_scope="raw finite-grid minimum; mesh changes are screening proxies, not certified error bounds or physical uncertainty",
            maximum_peak_grid_change_k=max(r["mesh_peak_change_k"] for r in rows),
            all_peak_grid_changes_within_0_1k=all(
                r["mesh_peak_change_k"] <= 0.1 for r in rows
            ),
        )
        print(
            profile,
            profiles[profile]["coldest_id"],
            profiles[profile]["maximum_peak_grid_change_k"],
            flush=True,
        )
    name, case, grids = samples[0]
    mirrored = relocate_design(
        case,
        {
            d.id: dict(
                x=case.package.width - d.bounds.x - d.bounds.width,
                y=case.package.height - d.bounds.y - d.bounds.height,
                rotation_deg=(d.rotation + 180) % 360,
            )
            for d in case.dies
        },
    )
    mirror_report, mirror_grids = decompose_sources(mirrored)
    mirror_errors = {
        n: float(np.nanmax(abs(grids[n][::-1, ::-1] - mirror_grids[n]))) for n in grids
    }
    if not all(
        np.array_equal(np.isnan(grids[n][::-1, ::-1]), np.isnan(mirror_grids[n]))
        for n in grids
    ):
        raise ValueError("mirror material masks differ")
    nominal = profiles["nominal"]["candidates"]
    legacy = json.loads((repo / "docs/evidence/v05-validation.json").read_text())[
        "layout_ranking"
    ]["candidates"]
    all_meshes = [
        m for p in profiles.values() for r in p["candidates"] for m in r["meshes"]
    ]
    checks = dict(
        nominal_reproduces_v05=all(
            a["id"] == b["id"] and abs(a["peak_c"] - b["peak_c"]) <= 1e-6
            for a, b in zip(nominal, legacy)
        ),
        all_power_only_networks_identical=all(
            m["all_source_matrices_identical"] for m in all_meshes
        ),
        pointwise_superposition=all(
            m["all_node_superposition_error_k"] <= 1e-8 for m in all_meshes
        ),
        nominal_peak_mesh_convergence=profiles["nominal"][
            "all_peak_grid_changes_within_0_1k"
        ],
        all_boundary_profiles_peak_mesh_convergence=all(
            p["all_peak_grid_changes_within_0_1k"] for p in profiles.values()
        ),
        package_rotation_symmetry=max(mirror_errors.values()) <= 1e-8,
        residual_and_heat_balance=all(
            m["total_linear_residual_inf_w"] <= 1e-8
            and abs(m["total_energy_balance_error_w"]) <= 3e-8
            and all(
                c["linear_residual_inf_w"] <= 1e-8
                and abs(c["energy_balance_error_w"]) <= 3e-8
                for c in m["source_checks"]
            )
            for m in all_meshes
        ),
    )
    comparisons = {}
    for label, indices in (
        ("rigid_translation", (0, 12, 24)),
        ("rx_relative_motion", (10, 13, 16)),
    ):
        selected = [nominal[i] for i in indices]
        a, b = selected[0], selected[-1]
        comparisons[label] = dict(
            layout_ids=[r["id"] for r in selected],
            peak_temperature_change_k=b["peak_c"] - a["peak_c"],
            source_contribution_changes_k={
                n: b["hotspot"]["source_contributions_k"][n]
                - a["hotspot"]["source_contributions_k"][n]
                for n in ("tx", "rx")
            },
            sampling="each layout's total-field hotspot; locations can differ",
        )
    for p in profiles.values():
        p["order_reversals_vs_nominal"] = [
            dict(
                a=a["id"],
                b=b["id"],
                beyond_sum_of_mesh_change_proxies=abs(a["peak_c"] - b["peak_c"])
                > a["mesh_peak_change_k"] + b["mesh_peak_change_k"]
                and abs(nominal[i]["peak_c"] - nominal[j]["peak_c"])
                > nominal[i]["mesh_peak_change_k"] + nominal[j]["mesh_peak_change_k"],
            )
            for (i, a), (j, b) in itertools.combinations(enumerate(p["candidates"]), 2)
            if (a["peak_c"] - b["peak_c"])
            * (nominal[i]["peak_c"] - nominal[j]["peak_c"])
            < 0
        ]
    source_files = [
        "tools/validate_thermal_decomposition.py",
        "tools/validation/factorial.py",
        "tools/validation/sources.py",
    ] + [
        "src/chiplet_floorplanning/" + n + ".py"
        for n in (
            "thermal_decomposition",
            "package",
            "power",
            "model",
            "mesh",
            "layout",
            "thermal",
            "interconnect",
        )
    ]
    report = dict(
        software_checks_passed=all(checks.values()),
        checks=checks,
        profiles=profiles,
        comparisons=comparisons,
        symmetry=dict(errors_k=mirror_errors, report=mirror_report),
        source=git_revision(repo),
        environment=dict(
            python=platform.python_version(),
            numpy=np.__version__,
            scipy=scipy.__version__,
        ),
        source_code_sha256={
            p: hashlib.sha256((repo / p).read_bytes()).hexdigest() for p in source_files
        },
        input_sha256=hashlib.sha256(
            (repo / "examples/low_speed_gpio.json").read_bytes()
        ).hexdigest(),
        total_wall_s=perf_counter() - started,
        independent_linear_solves=len(all_meshes) * 3 + 3,
        timing_status="not_evaluated",
        external_thermal_validation=dict(
            status="not_run",
            scope="E1 uses the internal linear solver; prior MFIT comparisons do not independently validate these source-decomposition cases",
        ),
        physical_calibration=False,
        complete_package_signoff=False,
        scope="E1 conditional linear-model decomposition; synthetic workload/cooling, not causal ANOVA or E2/E3 proof",
    )
    write_json(args.output / "report.json", report)
    compact = copy.deepcopy(report)
    for p in compact["profiles"].values():
        p["initial_maximum_peak_grid_change_k"] = max(
            r["initial_peak_grid_change_k"] for r in p["candidates"]
        )
        for row in p["candidates"]:
            del row["meshes"]
    compact["maximum_numerical_errors"] = {
        k: max(abs(m[k]) for m in all_meshes)
        for k in (
            "all_node_superposition_error_k",
            "total_linear_residual_inf_w",
            "total_energy_balance_error_w",
        )
    }
    compact["raw_report_sha256"] = hashlib.sha256(
        (args.output / "report.json").read_bytes()
    ).hexdigest()
    write_json(args.output / "summary.json", compact)
    plot_contributions(samples, args.output)
    print(
        json.dumps(dict(checks=checks, comparisons=comparisons), indent=2), flush=True
    )
    return 0 if report["software_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
