"""Predeclared placement ranking and independent data/clock route experiment."""

import argparse
import itertools
import json
from pathlib import Path

from chiplet_floorplanning.cli import source_revision
from chiplet_floorplanning.model import load_case, parse_case
from chiplet_floorplanning.layout import place_design, evaluate_layout
from chiplet_floorplanning.timing import run_timing
from chiplet_floorplanning.interconnect import estimate_links
from prepare_characterization import prepare
from validation.sources import write_json


def rank_summary(rows, weight):
    legal = [
        r
        for r in rows
        if r["timing_status"] == "analyzed" and r["timing_constraints_met"]
    ]

    def score(r):
        return weight * (r["peak_c"] - 25) / 10 - (1 - weight) * r["worst_slack_ns"]

    ordered = sorted(legal, key=lambda r: (score(r), r["id"]))
    best = ordered[0]
    # Final mesh change is a diagnostic uncertainty proxy, not a rigorous bound.
    indistinguishable = [
        r["id"]
        for r in ordered
        if abs(score(r) - score(best))
        <= weight * (r["mesh_peak_change_k"] + best["mesh_peak_change_k"]) / 10
        + (1 - weight) * 2e-6
    ]
    return dict(
        thermal_weight=weight,
        order=[r["id"] for r in ordered],
        best_id=best["id"],
        numerically_indistinguishable_from_best=indistinguishable,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("local"))
    parser.add_argument(
        "--sta", type=Path, default=Path("local/upstream/OpenSTA/app/sta")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    prepare(args.root)
    pdk = args.root / "pdk-v03"
    opts = dict(
        sta=args.sta,
        sky_lib=args.root / "pdk/sky130_tt_1v8.lib",
        gf_lib=pdk / "gf_core_tt_3v3.lib",
        sky_pad_lib=pdk / "sky_io_tt_1v8_3v3.lib",
        gf_pad_lib=pdk / "gf_bi_t_tt_3v3_assembled.lib",
        pad_direction="gf180_to_sky130",
        period_ns=20,
    )
    base = load_case("examples/low_speed_gpio.json")

    def timing(case, out):
        try:
            result = run_timing(case, out, **opts)
            return dict(
                timing_status="analyzed",
                setup_slack_ns=result["setup_slack_ns"],
                hold_slack_ns=result["hold_slack_ns"],
                worst_slack_ns=min(result["setup_slack_ns"], result["hold_slack_ns"]),
                timing_constraints_met=result["timing_constraints_met"],
            )
        except ValueError as error:
            if not (out / "rejection.json").exists():
                raise  # An unexpected software error must not become an electrical rejection.
            return dict(timing_status="electrically_rejected", reason=str(error))

    rows = []
    for index, (tx, rx, y) in enumerate(
        itertools.product((0.5, 1.5, 2.5), (6, 7, 8), (1, 2, 3))
    ):
        name = f"layout_{index:02d}"
        out = args.output / name
        out.mkdir()
        placement = dict(tx=dict(x=tx, y=y), rx=dict(x=rx, y=2))
        metrics = []
        for nx, ny in ((48, 32), (96, 64)):
            case = place_design(
                base,
                placement,
                corridors_y_mm=dict(lane_data=1.5, lane_clock=4.5),
                grid=dict(nx=nx, ny=ny, mode="geometry_conformal"),
            )
            evaluation = evaluate_layout(case)
            thermal = evaluation["thermal"]
            metrics.append(
                dict(
                    nx=case.nx,
                    ny=case.ny,
                    peak_c=thermal["peak_c"],
                    energy_balance_error_w=thermal["energy_balance_error_w"],
                )
            )
        write_json(out / "case.json", case.input_data)
        row = dict(
            id=name,
            placement_mm=placement,
            thermal_meshes=metrics,
            peak_c=metrics[-1]["peak_c"],
            mesh_peak_change_k=abs(metrics[-1]["peak_c"] - metrics[-2]["peak_c"]),
            links=estimate_links(case),
            **timing(case, out / "sta"),
        )
        rows.append(row)
        write_json(out / "report.json", row)
        print(name, row["timing_status"], flush=True)
    sweeps = []
    # One length changes at a time; retain paired common-delay control.
    for kind in ("data", "clock", "both"):
        for extra in (0.0, 1.0, 2.0, 4.0, 8.0, 12.0):
            # Nominal ports have y_data=2.6 and y_clock=3.4 mm. Moving
            # corridors outward by extra/2 adds exactly extra route length.
            corridors = dict(lane_data=2.6, lane_clock=3.4)
            if kind in ("data", "both"):
                # Alternate upper/lower corridor to fit up to 12 mm detour.
                corridors["lane_data"] = 2.6 + extra / 2
            if kind in ("clock", "both"):
                corridors["lane_clock"] = 3.4 + extra / 2
            # The 8 mm high package bounds route detours; use lower corridor
            # for the longest clock case if possible; otherwise expand only
            # this sensitivity harness package (never ranking candidates).
            raw = json.loads(json.dumps(base.input_data))
            raw["package_mm"]["height"] = max(8.0, max(corridors.values()))
            case = place_design(parse_case(raw), {}, corridors_y_mm=corridors)
            name = f"{kind}_extra_{extra:g}mm"
            result = dict(
                id=name,
                changed=kind,
                extra_length_mm=extra,
                links=estimate_links(case),
                **timing(case, args.output / name),
            )
            sweeps.append(result)
    legal = [
        r
        for r in rows
        if r["timing_status"] == "analyzed" and r["timing_constraints_met"]
    ]
    if not legal:
        raise ValueError(
            "no electrically and temporally legal layouts; ranking gate blocked"
        )
    conflicts = []
    thermal_ties = timing_ties = 0
    mesh_order_reversals = []
    for a, b in itertools.combinations(legal, 2):
        dt = a["peak_c"] - b["peak_c"]
        ds = a["worst_slack_ns"] - b["worst_slack_ns"]
        thermal_tie = abs(dt) <= a["mesh_peak_change_k"] + b["mesh_peak_change_k"]
        timing_tie = (
            abs(ds) <= 2e-6
        )  # Conservative printed report precision, not model uncertainty.
        thermal_ties += thermal_tie
        timing_ties += timing_tie
        coarse_dt = a["thermal_meshes"][0]["peak_c"] - b["thermal_meshes"][0]["peak_c"]
        if coarse_dt * dt < 0:
            mesh_order_reversals.append(
                dict(a=a["id"], b=b["id"], within_mesh_change_proxy=thermal_tie)
            )
        if not thermal_tie and not timing_tie and dt * ds > 0:
            conflicts.append(
                dict(
                    a=a["id"],
                    b=b["id"],
                    temperature_difference_k=dt,
                    margin_difference_ns=ds,
                )
            )
    checks = dict(
        all_27_placements_geometry_legal=len(rows) == 27,
        thermal_mesh_change_below_0_1k=all(
            r["mesh_peak_change_k"] <= 0.1 for r in rows
        ),
        energy_balance=all(
            abs(m["energy_balance_error_w"]) <= 3e-8
            for r in rows
            for m in r["thermal_meshes"]
        ),
        independent_route_lengths=all(
            all(
                abs(
                    l["modeled_length_mm"]
                    - (
                        3
                        + (
                            s["extra_length_mm"]
                            if s["changed"] in (l["kind"], "both")
                            else 0
                        )
                    )
                )
                < 1e-10
                for l in s["links"]
            )
            for s in sweeps
        ),
    )
    by_sweep = {(s["changed"], s["extra_length_mm"]): s for s in sweeps}
    nominal = by_sweep["data", 0.0]
    data = by_sweep["data", 1.0]
    clock = by_sweep["clock", 1.0]
    both = by_sweep["both", 1.0]
    checks["independent_skew_signs"] = (
        data["setup_slack_ns"] < nominal["setup_slack_ns"] < clock["setup_slack_ns"]
        and clock["hold_slack_ns"] < nominal["hold_slack_ns"] < data["hold_slack_ns"]
    )
    checks["common_route_setup_cancellation_at_printed_precision"] = (
        abs(both["setup_slack_ns"] - nominal["setup_slack_ns"]) <= 2e-6
    )
    report = dict(
        passed=all(checks.values()),
        checks=checks,
        source_revision=source_revision(),
        candidates=rows,
        sensitivity_sweeps=sweeps,
        rankings=[rank_summary(rows, w) for w in (0, 0.25, 0.5, 0.75, 1)],
        numerically_resolved_conflicting_pairs=conflicts,
        thermal_order_reversals_on_refinement=mesh_order_reversals,
        thermal_tied_pairs=thermal_ties,
        timing_tied_pairs=timing_ties,
        physical_model_uncertainty="unknown; not bounded by mesh convergence",
        coupled_hot_pad_timing=False,
        complete_package_signoff=False,
        scope="Independent steady thermal and TT25 GPIO timing objectives; not temperature-dependent pad STA",
        optimizer_gate="Physical thermal-timing ranking advantage not established without a consistent temperature-dependent interface model",
    )
    write_json(args.output / "report.json", report)
    print(
        json.dumps(
            dict(
                passed=report["passed"],
                checks=checks,
                accepted=len(legal),
                resolved_conflicts=len(conflicts),
            )
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
