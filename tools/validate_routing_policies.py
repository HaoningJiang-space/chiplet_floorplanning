"""Fixed-placement legal-routing counterfactual; no fabricated timing pressure."""

import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.interconnect import estimate_links
from chiplet_floorplanning.layout import (
    corridor_routes,
    evaluate_layout,
    relocate_design,
)
from chiplet_floorplanning.model import load_case
from chiplet_floorplanning.routing import (
    PlanarRules,
    audit_routes,
    shortest_route_pairs,
    with_routes,
)
from chiplet_floorplanning.timing import run_timing
from prepare_characterization import prepare
from validation.ranking import common_cohort, compare_reference, summarize
from validation.sources import git_revision, verify, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("local"))
    parser.add_argument(
        "--sta", type=Path, default=Path("local/upstream/OpenSTA/app/sta")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--reference-ranking",
        type=Path,
        required=True,
        help="report.json from validate_layout_ranking.py using this STA build and libraries",
    )
    args = parser.parse_args()
    started = perf_counter()
    args.output.mkdir(parents=True, exist_ok=False)
    verify(args.root, "pdk/sky130_tt_1v8.lib")
    assembly = prepare(args.root)
    repo = Path(__file__).resolve().parents[1]
    base = load_case(repo / "examples/low_speed_gpio.json")
    contract = json.loads((repo / "examples/planar_routing_contract.json").read_text())
    rules = PlanarRules.from_dict(contract)
    pdk = args.root / "pdk-v03"
    options = dict(
        sta=args.sta,
        sky_lib=args.root / "pdk/sky130_tt_1v8.lib",
        gf_lib=pdk / "gf_core_tt_3v3.lib",
        sky_pad_lib=pdk / "sky_io_tt_1v8_3v3.lib",
        gf_pad_lib=pdk / "gf_bi_t_tt_3v3_assembled.lib",
        pad_direction="gf180_to_sky130",
        period_ns=20,
    )
    policies = {p: [] for p in ("R1", "R2", "R3", "R4")}
    placements, evaluated_routes, profile = [], [], []
    sta_identity = None

    def evaluate_route(case, route_id, routes, folder):
        nonlocal sta_identity
        begin = perf_counter()
        timings = {}
        routed = with_routes(case, routes, timings_s=timings)
        audit = audit_routes(routed, rules)
        links = estimate_links(routed)
        record = dict(
            route_id=route_id,
            case_input_sha256=hashlib.sha256(
                json.dumps(routed.input_data, sort_keys=True).encode()
            ).hexdigest(),
            route_points_mm=routes,
            routing=audit,
            route_lengths_mm={l["kind"]: l["modeled_length_mm"] for l in links},
            manhattan_lower_bounds_mm={
                l["kind"]: l["manhattan_length_mm"] for l in links
            },
            total_length_mm=sum(l["modeled_length_mm"] for l in links),
            timing_status="geometry_rejected",
            sta_invoked=False,
        )
        folder.mkdir()
        write_json(folder / "case.json", routed.input_data)
        if audit["geometry_legal"]:
            record["sta_invoked"] = True
            sta_begin = perf_counter()
            try:
                result = run_timing(
                    routed, folder / "sta", **options, timings_s=timings
                )
                identity = {
                    key: result[key]
                    for key in (
                        "tool_version",
                        "sta_sha256",
                        "libraries",
                        "period_ns",
                        "pad_mode",
                        "interface",
                    )
                }
                if sta_identity is not None and sta_identity != identity:
                    raise RuntimeError("STA executable or libraries changed during run")
                sta_identity = identity
                record.update(
                    timing_status="analyzed",
                    setup_slack_ns=result["setup_slack_ns"],
                    hold_slack_ns=result["hold_slack_ns"],
                    worst_slack_ns=min(
                        result["setup_slack_ns"], result["hold_slack_ns"]
                    ),
                    timing_constraints_met=result["timing_constraints_met"],
                    sta_input_sha256=result["input_sha256"],
                )
            except ValueError as error:
                if not (folder / "sta/rejection.json").exists():
                    raise
                record.update(
                    timing_status="electrically_rejected", rejection_reason=str(error)
                )
            timings["sta_wrapper_total_s"] = perf_counter() - sta_begin
        timings["route_evaluation_total_s"] = perf_counter() - begin
        record["performance_s"] = timings
        profile.append(dict(kind="route", **timings))
        write_json(folder / "report.json", record)
        return record

    for index, (tx, rx, y) in enumerate(
        itertools.product((0.5, 1.5, 2.5), (6, 7, 8), (1, 2, 3))
    ):
        name = f"layout_{index:02d}"
        folder = args.output / name
        folder.mkdir()
        placement = dict(tx=dict(x=tx, y=y), rx=dict(x=rx, y=2))
        meshes = []
        for nx, ny in ((48, 32), (96, 64)):
            timings = {}
            case = relocate_design(
                base,
                placement,
                grid=dict(nx=nx, ny=ny, mode="geometry_conformal"),
                timings_s=timings,
            )
            result = evaluate_layout(case, timings_s=timings)
            thermal = result["thermal"]
            meshes.append(
                dict(
                    nx=case.nx,
                    ny=case.ny,
                    peak_c=thermal["peak_c"],
                    energy_balance_error_w=thermal["energy_balance_error_w"],
                    performance_s=timings,
                )
            )
            profile.append(dict(kind="thermal", **timings))
        fixed = dict(
            id=name,
            placement_mm=placement,
            peak_c=meshes[-1]["peak_c"],
            mesh_peak_change_k=abs(meshes[-1]["peak_c"] - meshes[0]["peak_c"]),
            thermal_meshes=meshes,
            S_T_ns=None,
            thermal_pair_interaction_ns=None,
            thermal_reuse_scope="only routes of this exact placement/power/stack/mesh; wire heat and metal-pattern conductivity absent",
        )
        placements.append(fixed)
        route_begin = perf_counter()
        pairs = shortest_route_pairs(case, rules)
        portfolio = {}
        if pairs:
            portfolio["R1"] = pairs[0]["routes"]
        portfolio["R2"] = corridor_routes(case, dict(lane_data=1.5, lane_clock=4.5))
        portfolio["R3"] = corridor_routes(case, dict(lane_data=4.5, lane_clock=1.5))
        for data_y, clock_y in itertools.product((1.5, 2.5, 3.5), (2.5, 3.5, 4.5)):
            portfolio[f"data_{data_y}_clock_{clock_y}"] = corridor_routes(
                case, dict(lane_data=data_y, lane_clock=clock_y)
            )
        profile.append(
            dict(
                kind="routing_generation",
                routing_generation_s=perf_counter() - route_begin,
            )
        )
        records, identical = {}, {}
        for route_id, routes in portfolio.items():
            key = json.dumps(routes, sort_keys=True)
            if key in identical:
                records[route_id] = {
                    **copy.deepcopy(records[identical[key]]),
                    "alias_of": identical[key],
                    "route_id": route_id,
                }
            else:
                records[route_id] = evaluate_route(
                    case, route_id, routes, folder / route_id
                )
                identical[key] = route_id
                evaluated_routes.append(dict(layout_id=name, **records[route_id]))
        for policy in ("R1", "R2", "R3"):
            record = records.get(
                policy,
                dict(
                    route_id=policy,
                    timing_status="geometry_rejected",
                    sta_invoked=False,
                    routing=dict(geometry_legal=False, issues=["no route pair found"]),
                ),
            )
            policies[policy].append({**fixed, **record})
        electrical = [r for r in records.values() if r["timing_status"] == "analyzed"]
        feasible = [r for r in electrical if r["timing_constraints_met"]]
        if feasible:
            selected = min(
                feasible, key=lambda r: (r["total_length_mm"], r["route_id"])
            )
        elif electrical:
            selected = max(electrical, key=lambda r: r["worst_slack_ns"])
        else:
            selected = records["R2"]
        policies["R4"].append(
            dict(
                fixed,
                **selected,
                selected_route_id=selected["route_id"],
                portfolio_unique_route_count=len(identical),
                portfolio_feasible_count=len(
                    {json.dumps(r["route_points_mm"], sort_keys=True) for r in feasible}
                ),
                achievable_worst_slack_range_ns=(
                    [
                        min(r["worst_slack_ns"] for r in electrical),
                        max(r["worst_slack_ns"] for r in electrical),
                    ]
                    if electrical
                    else None
                ),
                selection="first require feasibility, then minimum total wirelength within finite portfolio; infeasible best-margin witness retained",
            )
        )
        write_json(folder / "portfolio.json", records)
        print(name, {p: policies[p][-1]["timing_status"] for p in policies}, flush=True)
    summaries = {p: summarize(rows) for p, rows in policies.items()}
    legacy = json.loads((repo / "docs/evidence/v05-validation.json").read_text())[
        "layout_ranking"
    ]["candidates"]
    same_build_reference = compare_reference(
        policies["R2"], args.reference_ranking, sta_identity
    )
    historical_differences = [
        dict(
            id=a["id"],
            **{key: a[key] - b[key] for key in ("setup_slack_ns", "hold_slack_ns")},
        )
        for a, b in zip(policies["R2"], legacy)
        if a["timing_status"] == b["timing_status"] == "analyzed"
    ]
    checks = dict(
        reference_policy_coverage=all(
            len(policies[p]) == 27
            and all(r["timing_status"] == "analyzed" for r in policies[p])
            for p in ("R1", "R4")
        )
        and all(r["timing_status"] == "geometry_rejected" for r in policies["R3"]),
        r1_attains_independent_manhattan_lower_bound=all(
            abs(r["total_length_mm"] - sum(r["manhattan_lower_bounds_mm"].values()))
            < 1e-9
            for r in policies["R1"]
        ),
        thermal_refinement=all(r["mesh_peak_change_k"] <= 0.1 for r in placements),
        thermal_energy_balance=all(
            abs(m["energy_balance_error_w"]) <= 3e-8
            for r in placements
            for m in r["thermal_meshes"]
        ),
        r2_reproduces_same_build_reference=same_build_reference["passed"],
        thermal_reproduces_prior_candidates=all(
            abs(a["peak_c"] - b["peak_c"]) < 1e-6 for a, b in zip(placements, legacy)
        ),
        no_geometrically_rejected_route_sent_to_sta=all(
            not r["sta_invoked"]
            for r in evaluated_routes
            if not r["routing"]["geometry_legal"]
        ),
        all_analyzed_routes_geometrically_valid=all(
            r["routing"]["geometry_legal"]
            for r in evaluated_routes
            if r["timing_status"] == "analyzed"
        ),
        profiling_finite_nonnegative=all(
            np.isfinite(v) and v >= 0
            for r in profile
            for k, v in r.items()
            if k.endswith("_s")
        ),
    )
    phases = sorted({k for r in profile for k in r if k.endswith("_s")})
    statistics = {
        k: dict(
            count=sum(k in r for r in profile),
            total_s=sum(r.get(k, 0) for r in profile),
            median_s=float(np.median([r[k] for r in profile if k in r])),
            maximum_s=max(r[k] for r in profile if k in r),
        )
        for k in phases
    }
    code = list((repo / "src/chiplet_floorplanning").glob("*.py")) + [
        Path(__file__).resolve(),
        repo / "tools/prepare_characterization.py",
        repo / "tools/validation/ranking.py",
        repo / "tools/validation/sources.py",
    ]
    report = dict(
        software_checks_passed=all(checks.values()),
        checks=checks,
        source=git_revision(repo),
        source_code_sha256={
            str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in code
        },
        input_files_sha256={
            path: hashlib.sha256((repo / path).read_bytes()).hexdigest()
            for path in (
                "examples/low_speed_gpio.json",
                "examples/planar_routing_contract.json",
                "docs/evidence/v05-validation.json",
                "tools/sources.lock.json",
            )
        },
        sta_identity=sta_identity,
        same_build_reference=same_build_reference,
        historical_r2_slack_differences_ns=historical_differences,
        historical_comparison_scope="diagnostic across builds; no physical-error tolerance inferred",
        assembly=assembly,
        routing_contract=contract,
        placements=placements,
        policies=policies,
        summaries=summaries,
        common_accepted_cohort=common_cohort(policies),
        unique_route_evaluations=len(evaluated_routes),
        sta_invocations=sum(r["sta_invoked"] for r in evaluated_routes),
        performance=dict(
            phase_statistics=statistics,
            samples=profile,
            total_wall_s=perf_counter() - started,
            scope="single-run wall times; no cross-placement thermal-matrix cache and no STA-result cache",
        ),
        timing_requirement=dict(
            period_ns=20,
            frequency_mhz=50,
            provenance="unchanged v0.5 demonstration assumption, not sourced protocol requirement",
            timing_critical_benchmark_admitted=False,
        ),
        S_T_status="missing: same-interface hot-pad gate failed",
        thermal_pair_interaction_ns=None,
        joint_optimization_necessity_established=False,
        physical_model_error="unbounded; geometry and numerical convergence are not physical validation",
        complete_package_signoff=False,
    )
    write_json(args.output / "report.json", report)
    print(
        json.dumps(
            dict(
                software_checks_passed=report["software_checks_passed"],
                checks=checks,
                policies={
                    p: {
                        k: s[k]
                        for k in (
                            "geometrically_and_electrically_legal_count",
                            "timing_feasible_count",
                            "constrained_thermal_optimum",
                            "conflict_count",
                            "conflict_count_above_1ps",
                        )
                    }
                    for p, s in summaries.items()
                },
            ),
            indent=2,
        )
    )
    return 0 if report["software_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
