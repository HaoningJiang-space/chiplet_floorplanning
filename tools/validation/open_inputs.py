"""Strict conversion of pinned public examples; not a general format importer."""

import copy
import csv
import json
from pathlib import Path
import numpy as np
import yaml


def conductivity(material):
    k = material["thermal_conductivity"]
    return (
        {"conductivity_xyz_w_mk": [k[a] for a in ("kx", "ky", "kz")]}
        if isinstance(k, dict)
        else {"conductivity_w_mk": k}
    )


def mfit_case(folder, materials_path):
    geometry = yaml.safe_load(next(folder.glob("chiplet_geometry*.yml")).read_text())
    powers = yaml.safe_load(next(folder.glob("power_dist*.yml")).read_text())
    materials = yaml.safe_load(materials_path.read_text())
    trace = {
        row[0]: np.asarray(row[1:], float)
        for row in csv.reader(next(folder.glob("power_seq*.csv")).open())
    }
    if len({len(values) for values in trace.values()}) != 1:
        raise ValueError("power trace lengths differ")
    if any(
        np.any(~np.isfinite(v)) or np.any(v < 0) or np.any(v > 100)
        for v in trace.values()
    ):
        raise ValueError("invalid power percentage")
    cfg = geometry["common"]
    powered = [name for name, layer in geometry["layers"].items() if layer["power_src"]]
    if len(powered) != 1:
        raise ValueError("adapter requires one source layer")
    power_layer = powered[0]
    dies = []
    for name, die in powers[power_layer].items():
        width = die.get("length_chiplet_x", cfg["chiplet_x"])
        height = die.get("length_chiplet_y", cfg["chiplet_y"])
        blocks = []
        for bid, block in die["layout_blocks"].items():
            values = trace[f"{power_layer}_{name}_{bid}"]
            blocks.append(
                {
                    "id": bid,
                    "rect_mm": dict(
                        x=block["start_point_x"],
                        y=block["start_point_y"],
                        width=block["length_x"],
                        height=block["length_y"],
                    ),
                    "power_w": float(block["max_power"] * values.mean() / 100),
                    "provenance": f"MFIT supplied percentage trace, arithmetic mean of all {len(values)} equally weighted samples times declared max_power; not measured power.",
                }
            )
        dies.append(
            dict(
                id=name,
                size_mm=dict(width=width, height=height),
                placement_mm=dict(x=die["start_chiplet_x"], y=die["start_chiplet_y"]),
                rotation_deg=0,
                blocks=blocks,
                ports_mm={},
            )
        )
    layers, z = [], 0.0
    for name, source in geometry["layers"].items():
        if not np.isclose(source["start_point"]["z"], z, rtol=0, atol=1e-12):
            raise ValueError("noncontiguous z stack")
        z += source["thickness"]
        item = dict(
            id=name,
            thickness_mm=source["thickness"],
            **conductivity(materials[source["material"]]),
        )
        if source["nodes"]["under_chiplet"]:
            item["footprint"] = "chiplets"
            if name in powers:
                if set(powers[name]) != {d["id"] for d in dies}:
                    raise ValueError("layer islands differ from source dies")
                for die in dies:
                    island = powers[name][die["id"]]
                    if any(
                        not np.isclose(
                            island.get(key, default), expected, rtol=0, atol=1e-12
                        )
                        for key, default, expected in (
                            ("start_chiplet_x", 0, die["placement_mm"]["x"]),
                            ("start_chiplet_y", 0, die["placement_mm"]["y"]),
                            (
                                "length_chiplet_x",
                                cfg["chiplet_x"],
                                die["size_mm"]["width"],
                            ),
                            (
                                "length_chiplet_y",
                                cfg["chiplet_y"],
                                die["size_mm"]["height"],
                            ),
                        )
                    ):
                        raise ValueError("per-layer island geometry unsupported")
                    if "material" in island:
                        item.setdefault("die_materials", {})[die["id"]] = conductivity(
                            materials[island["material"]]
                        )
        else:
            x, y = (source["start_point"][a] for a in ("x", "y"))
            item["footprint"] = "package" if x == y == 0 else "rectangle"
            if item["footprint"] == "rectangle":
                item["rect_mm"] = dict(
                    x=x,
                    y=y,
                    width=cfg["x_length"] - 2 * x,
                    height=cfg["y_length"] - 2 * y,
                )
        layers.append(item)
    if not np.isclose(z, cfg["z_length"], rtol=0, atol=1e-12):
        raise ValueError("package height mismatch")
    return dict(
        schema_version=1,
        name=folder.name,
        package_mm=dict(width=cfg["x_length"], height=cfg["y_length"]),
        grid=dict(nx=19, ny=19, mode="uniform"),
        chiplets=dies,
        thermal=dict(
            model="layered_package_steady",
            layers=layers,
            power_layer=power_layer,
            ambient_c=cfg["ambient_temp"] - 273.15,
            top_h_w_m2k=cfg["bc_top_htc"],
            bottom_h_w_m2k=cfg["bc_bottom_htc"],
            provenance="MFIT pinned example stack, materials and convection; remeshed mean trace steady state, not original transient.",
        ),
        interconnect=dict(
            model="manhattan_lower_bound",
            r_ohm_per_mm=0,
            c_pf_per_mm=0,
            provenance="No electrical model or timing paths in thermal reference example.",
        ),
        links=[],
    )


def rapidchiplet_case(folder):
    def read(group, name):
        return json.loads((folder / "inputs" / group / name).read_text())

    inputs = dict(
        design={},
        chiplets=read("chiplets", "chiplets_example_experiment.json"),
        placement=read("placements", "placement_example_experiment.json"),
        packaging=read("packagings", "example_packaging.json"),
        topology=read("topologies", "topology_example_experiment.json"),
    )
    dies = []
    for i, placement in enumerate(inputs["placement"]["chiplets"]):
        chip = inputs["chiplets"][placement["name"]]
        width, height = chip["dimensions"]["x"], chip["dimensions"]["y"]
        dies.append(
            dict(
                id=f"die{i}",
                size_mm=dict(width=width, height=height),
                placement_mm=placement["position"],
                rotation_deg=placement["rotation"],
                blocks=[
                    dict(
                        id="total",
                        rect_mm=dict(x=0, y=0, width=width, height=height),
                        power_w=chip["power"],
                        provenance="RapidChiplet input power, uniformly distributed by this adapter; no workload extraction.",
                    )
                ],
                ports_mm={
                    f"phy{j}": dict(x=p["x"], y=p["y"])
                    for j, p in enumerate(chip["phys"])
                },
            )
        )
    if (
        any(d["rotation_deg"] != 0 for d in dies)
        or inputs["placement"]["interposer_routers"]
    ):
        raise ValueError(
            "pinned placement adapter supports unrotated chiplets without routers"
        )
    size = {
        a: max(d["placement_mm"][p] + d["size_mm"][a] for d in dies)
        for a, p in [("width", "x"), ("height", "y")]
    }
    template = json.loads(Path("examples/layered_two_chiplets.json").read_text())
    thermal = copy.deepcopy(template["thermal"])
    thermal["provenance"] = (
        "Additional assumed demonstration stack/convection from layered_two_chiplets; RapidChiplet supplies no thermal ground truth."
    )
    links = []
    for i, link in enumerate(inputs["topology"]):
        endpoints = [
            dict(chiplet=f"die{link[k]['outer_id']}", port=f"phy{link[k]['inner_id']}")
            for k in ("ep1", "ep2")
        ]
        links.append(
            dict(id=f"link{i}", kind="data", source=endpoints[0], target=endpoints[1])
        )
    return (
        dict(
            schema_version=1,
            name="rapidchiplet_16_original",
            package_mm=size,
            grid=dict(nx=32, ny=32, mode="geometry_conformal"),
            chiplets=dies,
            thermal=thermal,
            interconnect=dict(
                model="manhattan_lower_bound",
                r_ohm_per_mm=0,
                c_pf_per_mm=0,
                provenance="Geometry-only architectural links; zero RC placeholders are not timing models.",
            ),
            links=links,
        ),
        inputs,
    )
