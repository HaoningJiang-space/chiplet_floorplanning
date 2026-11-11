"""Compare independently assembled package networks against pinned MFIT classes.

MFIT's class body is executed without its unused binary transient-solver loader;
its Python geometry and network methods are unchanged. Dense NumPy solves the
MFIT steady matrix; our implementation assembles and solves a sparse matrix.
"""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

from chiplet_floorplanning.model import load_case, parse_case
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.package import assemble_package, solve_package


def reference(case, upstream, output):
    lock = json.loads(Path(__file__).with_name("sources.lock.json").read_text())
    for record in lock["files"]:
        if record["path"].startswith("upstream/mfit-source/"):
            path = upstream / Path(record["path"]).name
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError(f"MFIT source hash mismatch: {path.name}")
    sys.path.insert(0, str(upstream.resolve()))
    import common
    from layer_class import Layer_chiplet
    from power_class import Power_grid
    tree = ast.parse((upstream / "package_class.py").read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Chiplet_package")
    scope = {"common": common, "Layer_chiplet": Layer_chiplet, "np": np}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(upstream / "package_class.py"), "exec"), scope)
    cfg = case.thermal
    ztotal = sum(layer["thickness_mm"] for layer in cfg["layers"])
    settings = {"x_length": case.package.width, "y_length": case.package.height, "z_length": ztotal,
                "chiplet_x": 0, "chiplet_y": 0, "chiplet_spacing": 0, "n_chiplet_x": 0, "n_chiplet_y": 0,
                "bc_top_htc": cfg["top_h_w_m2k"], "bc_bottom_htc": cfg["bottom_h_w_m2k"], "ambient_temp": cfg["ambient_c"] + 273.15}
    geometry, powers, materials = {"common": settings, "layers": {}}, {}, {}
    dx, dy = case.package.width / case.nx, case.package.height / case.ny
    z = 0.0
    for layer in cfg["layers"]:
        name = layer["id"]
        materials[name] = {"thermal_conductivity": layer["conductivity_w_mk"], "density": 2330.0, "specific_heat": 710.0}
        geometry["layers"][name] = {"thickness": layer["thickness_mm"], "material": name,
            "power_src": name == cfg["power_layer"], "start_point": {"x": 0, "y": 0, "z": z},
            "nodes": {"uniform": True, "under_chiplet": layer["footprint"] == "chiplets", "x_nodes": case.nx, "y_nodes": case.ny}}
        z += layer["thickness_mm"]
        if layer["footprint"] == "chiplets":
            powers[name] = {}
            for die in case.dies:
                r = die.bounds
                item = {"start_chiplet_x": r.x, "start_chiplet_y": r.y, "length_chiplet_x": r.width,
                        "length_chiplet_y": r.height, "nodes_x": round(r.width / dx), "nodes_y": round(r.height / dy)}
                if name == cfg["power_layer"]:
                    item["layout_blocks"] = {}
                    for block in die.blocks:
                        b = die.transform(block.rect)
                        item["layout_blocks"][block.id] = {"start_point_x": b.x-r.x, "start_point_y": b.y-r.y,
                            "length_x": b.width, "length_y": b.height, "max_power": block.power_w}
                powers[name][die.id] = item
    trace = output / "mfit_power.csv"
    trace.write_text("".join(f"{layer}_{die}_{block},100\n" for layer, dies in powers.items()
                             for die, item in dies.items() for block in item.get("layout_blocks", {})))
    args = SimpleNamespace(is_homogeneous=False, use_tuned_C=False, generate_DSS=False, time_step=1.0,
                           simulation_type="steady", total_duration=1.0, power_interval=1.0,
                           power_seq_file=str(trace), generate_heatmap=False)
    grid = Power_grid(powers, args)
    grid.create_power_seq_grid(common.Utils(settings))
    package = scope["Chiplet_package"](materials, geometry, grid, args, common.Utils(settings))
    package.create_layers()
    package.connect_nodes()
    package.set_initial_conditions()
    coordinates = []
    for z, layer in enumerate(package.layers):
        cells = layer.nodes if layer.is_layer_under_chiplet() else [n for column in layer.nodes for n in column]
        coordinates.extend((z, round(n.y / dy), round(n.x / dx)) for n in cells)
    return package.conductance_all, package.power[:, 0], coordinates, geometry, powers, materials


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
