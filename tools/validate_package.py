"""Compare independently assembled package networks against pinned MFIT classes.

MFIT's class body is executed without its unused binary transient-solver loader;
its Python geometry and network methods are unchanged. Dense NumPy solves the
MFIT steady matrix; our implementation assembles and solves a sparse matrix.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.model import load_case, parse_case
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.package import assemble_package, solve_package


from validation.mfit import reference


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="examples/layered_two_chiplets.json")
    parser.add_argument("--mfit", type=Path, default=Path("local/upstream/mfit-source"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    case = load_case(args.case)
    raw = copy.deepcopy(case.input_data)
    raw["grid"] = {"nx": 12, "ny": 8}
    small = parse_case(raw)
    power, _ = rasterize(small)
    matrix, rhs, sink, nodes, _, _ = assemble_package(small, power)
    ref_matrix, ref_rhs, ref_nodes, geometry, powers, materials = reference(small, args.mfit, args.output)
    lookup = {node: i for i, node in enumerate(ref_nodes)}
    order = [lookup[node] for node in nodes]
    ref_matrix = ref_matrix[np.ix_(order, order)]
    ref_rhs = ref_rhs[order]
    _, own = solve_package(small, power)
    reference_temperature = np.linalg.solve(ref_matrix, ref_rhs) + small.thermal["ambient_c"]
    error = float(np.max(np.abs(reference_temperature - own["all_node_temperature_c"])))
    rhs_error = float(np.max(np.abs(ref_rhs - rhs)))
    matrix_error = float(np.max(np.abs(matrix.toarray() - ref_matrix)))
    ref_balance = float(ref_matrix.sum(axis=1) @ (reference_temperature-small.thermal["ambient_c"]) - ref_rhs.sum())
    meshes = []
    for nx, ny in [(24, 16), (48, 32), (96, 64)]:
        raw["grid"] = {"nx": nx, "ny": ny}
        fine = parse_case(raw)
        p, _ = rasterize(fine)
        _, result = solve_package(fine, p)
        meshes.append({"nx": nx, "ny": ny, "peak_c": result["peak_c"],
                       "energy_balance_error_w": result["energy_balance_error_w"]})
    mesh_change = abs(meshes[-1]["peak_c"]-meshes[-2]["peak_c"])
    passed = error <= 1e-7 and rhs_error <= 1e-10 and abs(ref_balance) <= 3e-8 and mesh_change <= 0.25
    report = {"passed": passed, "scope": "matched_equations_not_hardware_calibration",
              "reference": "MFIT Python network assembly; NumPy steady solve; no native transient binary",
              "mfit_commit": "4444336d95fe7e9a3bf440c96937831126c6a37f",
              "reference_source_hashes": {name: hashlib.sha256((args.mfit / name).read_bytes()).hexdigest()
                                          for name in ("common.py", "node_class.py", "layer_class.py", "power_class.py", "package_class.py")},
              "node_count": len(nodes), "max_temperature_error_k": error, "max_matrix_error_w_k": matrix_error,
              "max_power_error_w": rhs_error, "reference_heat_balance_error_w": ref_balance,
              "mesh_results": meshes, "last_mesh_peak_change_k": mesh_change}
    for name, data in [("report", report), ("mfit_geometry", geometry), ("mfit_power", powers), ("mfit_materials", materials)]:
        (args.output / f"{name}.json").write_text(json.dumps(data, indent=2, allow_nan=False)+"\n")
    np.savez(args.output / "comparison.npz", own_matrix=matrix.toarray(), reference_matrix=ref_matrix,
             power=rhs, reference_power=ref_rhs, reference_temperature=reference_temperature,
             own_temperature=own["all_node_temperature_c"])
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
