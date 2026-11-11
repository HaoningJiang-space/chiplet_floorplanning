"""Adapter to hash-verified, unchanged MFIT Python assembly (steady state only)."""

import ast
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
from chiplet_floorplanning.model import parse_rect
from chiplet_floorplanning.package import conductivity_xyz


def reference(case, upstream, output):
    if (
        not np.allclose(
            case.mesh.widths_mm, case.package.width / case.nx, rtol=0, atol=1e-12
        )
        or not np.allclose(
            case.mesh.heights_mm, case.package.height / case.ny, rtol=0, atol=1e-12
        )
        or any(
            layer.get("sidewall_contacts")
            or layer.get("contact_resistance_above_m2k_w", 0)
            for layer in case.thermal["layers"]
        )
    ):
        raise ValueError(
            "MFIT reference adapter requires uniform XY and zero contact resistance"
        )
    lock = json.loads(
        (Path(__file__).resolve().parents[1] / "sources.lock.json").read_text()
    )
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
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Chiplet_package"
    )
    scope = {"common": common, "Layer_chiplet": Layer_chiplet, "np": np}
    exec(
        compile(
            ast.Module(body=[cls], type_ignores=[]),
            str(upstream / "package_class.py"),
            "exec",
        ),
        scope,
    )
    cfg = case.thermal
    ztotal = sum(layer["thickness_mm"] for layer in cfg["layers"])
    settings = {
        "x_length": case.package.width,
        "y_length": case.package.height,
        "z_length": ztotal,
        "chiplet_x": 0,
        "chiplet_y": 0,
        "chiplet_spacing": 0,
        "n_chiplet_x": 0,
        "n_chiplet_y": 0,
        "bc_top_htc": cfg["top_h_w_m2k"],
        "bc_bottom_htc": cfg["bottom_h_w_m2k"],
        "ambient_temp": cfg["ambient_c"] + 273.15,
    }
    geometry, powers, materials = {"common": settings, "layers": {}}, {}, {}
    dx, dy = case.package.width / case.nx, case.package.height / case.ny
    z = 0.0
    for layer in cfg["layers"]:
        name = layer["id"]
        k = conductivity_xyz(layer)
        materials[name] = {
            "thermal_conductivity": dict(zip(("kx", "ky", "kz"), k)),
            "density": 2330.0,
            "specific_heat": 710.0,
        }
        rect = (
            parse_rect(layer["rect_mm"])
            if layer["footprint"] == "rectangle"
            else case.package
        )
        if (
            abs(2 * rect.x + rect.width - case.package.width) > 1e-10
            or abs(2 * rect.y + rect.height - case.package.height) > 1e-10
        ):
            raise ValueError("MFIT adapter supports symmetric offset rectangles only")
        geometry["layers"][name] = {
            "thickness": layer["thickness_mm"],
            "material": name,
            "power_src": name == cfg["power_layer"],
            "start_point": {"x": rect.x, "y": rect.y, "z": z},
            "nodes": {
                "uniform": True,
                "under_chiplet": layer["footprint"] == "chiplets",
                "x_nodes": round(rect.width / dx),
                "y_nodes": round(rect.height / dy),
            },
        }
        z += layer["thickness_mm"]
        if layer["footprint"] == "chiplets":
            powers[name] = {}
            for die in case.dies:
                r = die.bounds
                item = {
                    "start_chiplet_x": r.x,
                    "start_chiplet_y": r.y,
                    "length_chiplet_x": r.width,
                    "length_chiplet_y": r.height,
                    "nodes_x": round(r.width / dx),
                    "nodes_y": round(r.height / dy),
                }
                if die.id in layer.get("die_materials", {}):
                    material_name = name + "_" + die.id
                    materials[material_name] = dict(
                        materials[name],
                        thermal_conductivity=dict(
                            zip(
                                ("kx", "ky", "kz"),
                                conductivity_xyz(layer["die_materials"][die.id]),
                            )
                        ),
                    )
                    item["material"] = material_name
                if name == cfg["power_layer"]:
                    item["layout_blocks"] = {}
                    for block in die.blocks:
                        b = die.transform(block.rect)
                        item["layout_blocks"][block.id] = {
                            "start_point_x": b.x - r.x,
                            "start_point_y": b.y - r.y,
                            "length_x": b.width,
                            "length_y": b.height,
                            "max_power": block.power_w,
                        }
                powers[name][die.id] = item
    # MFIT tests top_z == package_z exactly. Python 3.12 sum uses improved
    # summation whereas sequential z += t does not; use the same boundary
    # construction on both sides, without changing any layer thickness.
    settings["z_length"] = z
    trace = output / "mfit_power.csv"
    trace.write_text(
        "".join(
            f"{layer}_{die}_{block},100\n"
            for layer, dies in powers.items()
            for die, item in dies.items()
            for block in item.get("layout_blocks", {})
        )
    )
    args = SimpleNamespace(
        is_homogeneous=False,
        use_tuned_C=False,
        generate_DSS=False,
        time_step=1.0,
        simulation_type="steady",
        total_duration=1.0,
        power_interval=1.0,
        power_seq_file=str(trace),
        generate_heatmap=False,
    )
    grid = Power_grid(powers, args)
    grid.create_power_seq_grid(common.Utils(settings))
    package = scope["Chiplet_package"](
        materials, geometry, grid, args, common.Utils(settings)
    )
    package.create_layers()
    package.connect_nodes()
    package.set_initial_conditions()
    coordinates = []
    for z, layer in enumerate(package.layers):
        cells = (
            layer.nodes
            if layer.is_layer_under_chiplet()
            else [n for column in layer.nodes for n in column]
        )
        coordinates.extend((z, round(n.y / dy), round(n.x / dx)) for n in cells)
    return (
        package.conductance_all,
        package.power[:, 0],
        coordinates,
        geometry,
        powers,
        materials,
    )
