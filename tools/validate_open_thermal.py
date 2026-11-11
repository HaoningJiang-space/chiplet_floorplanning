"""Open MFIT physical-input cases and RapidChiplet geometry, with separate gates."""

import argparse
from chiplet_floorplanning.cli import source_revision
import ast
import contextlib
import copy
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace
import numpy as np

from chiplet_floorplanning.model import parse_case
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.package import assemble_package, solve_package
from chiplet_floorplanning.interconnect import estimate_links
from validation.mfit import reference
from validation.open_inputs import mfit_case, rapidchiplet_case
from validation.sources import verify, write_json


def thermal_metrics(raw, nx, mode):
    raw = copy.deepcopy(raw)
    raw["grid"] = dict(nx=nx, ny=nx, mode=mode)
    case = parse_case(raw)
    power, blocks = rasterize(case)
    temp, result = solve_package(case, power)
    means = {}
    for record in blocks:
        r = record["package_rect_mm"]
        xs, ys = np.asarray(case.mesh.x_edges_mm), np.asarray(case.mesh.y_edges_mm)
        area = np.outer(
            np.maximum(
                0,
                np.minimum(ys[1:], r["y"] + r["height"]) - np.maximum(ys[:-1], r["y"]),
            ),
            np.maximum(
                0, np.minimum(xs[1:], r["x"] + r["width"]) - np.maximum(xs[:-1], r["x"])
            ),
        )
        active = area > 0
        means[record["chiplet"] + "/" + record["block"]] = float(
            np.sum(area[active] * temp[active]) / area.sum()
        )
    record = dict(
        requested_nx=nx,
        actual_nx=case.nx,
        actual_ny=case.ny,
        node_count=result["node_count"],
        peak_c=result["peak_c"],
        block_mean_c=means,
        total_power_w=float(power.sum()),
        power_mapping_error_w=float(
            power.sum() - sum(b.power_w for d in case.dies for b in d.blocks)
        ),
        energy_balance_error_w=result["energy_balance_error_w"],
    )
    return case, power, result, record


def convergence(raw, sizes, mode):
    rows = [thermal_metrics(raw, nx, mode)[3] for nx in sizes]
    a, b = rows[-2:]
    peak = abs(a["peak_c"] - b["peak_c"])
    mean = max(
        abs(a["block_mean_c"][k] - b["block_mean_c"][k]) for k in a["block_mean_c"]
    )
    return dict(
        meshes=rows,
        final_peak_change_k=peak,
        final_block_mean_change_k=mean,
        converged=peak <= 0.1 and mean <= 0.1,
        power_and_energy_passed=all(
            max(abs(r["power_mapping_error_w"]), abs(r["energy_balance_error_w"]))
            <= 1e-8 * r["total_power_w"]
            for r in rows
        ),
    )


def run_mfit(folder, root, output):
    raw = mfit_case(folder, root / "upstream/mfit-source/material_prop.yml")
    write_json(output / "case.json", raw)
    case, power, result, metric = thermal_metrics(raw, 19, "uniform")
    matrix, rhs, _, nodes, _, _ = assemble_package(case, power)
    with contextlib.redirect_stdout(io.StringIO()) as stream:
        ref, ref_rhs, ref_nodes, geo, powers, materials = reference(
            case, root / "upstream/mfit-source", output
        )
    (output / "reference.log").write_text(stream.getvalue())
    lookup = {node: i for i, node in enumerate(ref_nodes)}
    order = [lookup[node] for node in nodes]
    ref, ref_rhs = ref[np.ix_(order, order)], ref_rhs[order]
    sink_error = float(
        np.max(np.abs(np.asarray(matrix.sum(axis=1)).ravel() - ref.sum(axis=1)))
    )
    temperature = np.linalg.solve(ref, ref_rhs) + case.thermal["ambient_c"]
    errors = dict(
        max_boundary_conductance_error_w_k=sink_error,
        max_temperature_error_k=float(
            np.max(np.abs(temperature - result["all_node_temperature_c"]))
        ),
        max_matrix_error_w_k=float(np.max(np.abs(matrix.toarray() - ref))),
        max_power_error_w=float(np.max(np.abs(rhs - ref_rhs))),
    )
    for name, data in [
        ("mfit_geometry", geo),
        ("mfit_power", powers),
        ("mfit_materials", materials),
    ]:
        write_json(output / (name + ".json"), data)
    # Uniform refinement preserves all die/layer boundaries. Block powers use exact area overlap.
    conv = convergence(raw, [19, 38, 76], "uniform")
    if not conv["converged"]:
        coarse = conv
        conv = convergence(raw, [76, 152], "uniform")
        conv["earlier_meshes"] = coarse["meshes"]
    if not conv["converged"]:
        # Strongly localized block sources converge more slowly when their
        # edges cut cells. Retain the failed uniform check, then align sources.
        uniform = conv
        conv = convergence(raw, [76, 114, 152], "geometry_conformal")
        conv["unconverged_uniform_control"] = uniform
    report = dict(
        name=folder.name,
        chiplets=len(case.dies),
        blocks=sum(len(d.blocks) for d in case.dies),
        total_power_w=metric["total_power_w"],
        reference="Unchanged MFIT network, matched uniform remesh; not original transient or native solver",
        reference_nodes=len(nodes),
        errors=errors,
        convergence=conv,
        original_nonuniform_mesh_reproduced=False,
        physical_calibration=False,
        passed=sink_error <= 1e-12
        and errors["max_temperature_error_k"] <= 1e-7
        and errors["max_power_error_w"] <= 1e-10
        and conv["converged"]
        and conv["power_and_energy_passed"],
    )
    write_json(output / "report.json", report)
    return report


def run_rapid(root, output):
    folder = root / "open-cases/rapidchiplet"
    raw, inputs = rapidchiplet_case(folder)
    case = parse_case(raw)
    scope = dict(copy=copy, math=math)
    # Execute only the unchanged dependency-free upstream geometry routines.
    for file, functions in [("helpers.py", ("rotate_chiplet", "read_required_inputs"))]:
        tree = ast.parse((folder / file).read_text())
        nodes = [
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name in functions
        ]
        exec(
            compile(
                ast.Module(body=nodes, type_ignores=[]), str(folder / file), "exec"
            ),
            scope,
        )
    scope["hlp"] = SimpleNamespace(
        **{k: scope[k] for k in ("rotate_chiplet", "read_required_inputs")}
    )
    tree = ast.parse((folder / "rapidchiplet.py").read_text())
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "compute_link_lengths"
    )
    exec(
        compile(
            ast.Module(body=[fn], type_ignores=[]),
            str(folder / "rapidchiplet.py"),
            "exec",
        ),
        scope,
    )
    reference_lengths = scope["compute_link_lengths"](inputs, {})
    links = estimate_links(case)
    error = max(
        abs(
            own["modeled_length_mm"]
            - reference_lengths[
                (
                    (src["ep1"]["type"], src["ep1"]["outer_id"]),
                    (src["ep2"]["type"], src["ep2"]["outer_id"]),
                )
            ]
        )
        for own, src in zip(links, inputs["topology"])
    )
    conv = convergence(raw, [32, 64, 128], "geometry_conformal")
    write_json(output / "case.json", raw)
    report = dict(
        name=case.name,
        chiplets=len(case.dies),
        architectural_links=len(links),
        max_upstream_length_error_mm=error,
        convergence=conv,
        timing="not_evaluated_architectural_links_have_no_clock_constraints",
        thermal="assumed_stack_numerical_check_no_external_thermal_truth",
        physical_calibration=False,
        passed=error <= 1e-10 and conv["converged"] and conv["power_and_energy_passed"],
    )
    write_json(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("local"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for prefix in (
        "open-cases/mfit/",
        "open-cases/rapidchiplet/",
        "upstream/mfit-source/",
    ):
        hashes.update(verify(args.root, prefix))
    reports = []
    for folder in sorted((args.root / "open-cases/mfit").iterdir()):
        out = args.output / folder.name
        out.mkdir()
        report = run_mfit(folder, args.root, out)
        reports.append(report)
        print(folder.name, report["passed"], report["errors"], flush=True)
    out = args.output / "rapidchiplet"
    out.mkdir()
    reports.append(run_rapid(args.root, out))
    report = dict(
        source_revision=source_revision(),
        passed=all(r["passed"] for r in reports),
        cases=reports,
        source_hashes=hashes,
        complete_package_signoff=False,
    )
    write_json(args.output / "report.json", report)
    print(json.dumps({r["name"]: r["passed"] for r in reports}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
