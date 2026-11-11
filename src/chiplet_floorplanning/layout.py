"""Fixed-design placement and explicit corridor routing; no routing legality claim."""

import copy
from time import perf_counter

from .model import ModelError, parse_case, number
from .power import rasterize
from .thermal import solve_steady
from .interconnect import estimate_links


def relocate_design(design, placements_mm, *, grid=None, timings_s=None):
    """Move a fixed design and invalidate every prior explicit route."""
    raw = copy.deepcopy(design.input_data)
    die_ids = {d.id for d in design.dies}
    if set(placements_mm) - die_ids:
        raise ModelError("unknown placement die")
    for die in raw["chiplets"]:
        if die["id"] in placements_mm:
            placement = placements_mm[die["id"]]
            if (
                not isinstance(placement, dict)
                or set(placement) - {"x", "y", "rotation_deg"}
                or not {"x", "y"} <= set(placement)
            ):
                raise ModelError("placement needs x,y and optional rotation_deg")
            die["placement_mm"] = {k: placement[k] for k in ("x", "y")}
            die["rotation_deg"] = placement.get("rotation_deg", die["rotation_deg"])
    if grid is not None:
        raw["grid"] = copy.deepcopy(grid)
    for link in raw["links"]:
        link.pop("route_points_mm", None)
    return parse_case(raw, timings_s=timings_s)


def corridor_routes(placed, corridors_y_mm):
    """Construct ideal corridor polylines; geometric legality is a separate gate."""
    if set(corridors_y_mm) != {link["id"] for link in placed.links}:
        raise ModelError("every link requires an explicit corridor")
    dies = {d.id: d for d in placed.dies}
    routes = {}
    for link in placed.links:
        y = number(corridors_y_mm[link["id"]], "corridor_y_mm", minimum=0)
        endpoints = [
            dies[e["chiplet"]].point(*dies[e["chiplet"]].ports[e["port"]])
            for e in (link["source"], link["target"])
        ]
        a, b = endpoints
        if a[0] == b[0]:
            raise ModelError("corridor route requires distinct endpoint x coordinates")
        route = []
        for point in (a, (a[0], y), (b[0], y), b):
            if not route or point != tuple(route[-1]):
                route.append(list(point))
        routes[link["id"]] = route
    return routes


def place_design(design, placements_mm, *, corridors_y_mm, grid=None):
    """Compatibility corridor API; ideal paths carry no routing-legality claim."""
    from .routing import with_routes

    placed = relocate_design(design, placements_mm, grid=grid)
    return with_routes(placed, corridor_routes(placed, corridors_y_mm))


def evaluate_layout(case, *, timings_s=None):
    """In-memory thermal and route evaluation, with explicit missing timing."""
    started = perf_counter()
    power, blocks = rasterize(case)
    if timings_s is not None:
        timings_s["power_mapping_s"] = perf_counter() - started
    temperature, thermal = solve_steady(case, power, timings_s=timings_s)
    return dict(
        temperature_c=temperature,
        thermal=thermal,
        blocks=blocks,
        links=estimate_links(case),
        timing_status="not_evaluated",
        complete_package_signoff=False,
    )
