"""Fixed-design placement and explicit corridor routing; no routing legality claim."""

import copy

from .model import ModelError, parse_case, number
from .power import rasterize
from .thermal import solve_steady
from .interconnect import estimate_links


def place_design(design, placements_mm, *, corridors_y_mm, grid=None):
    """Return a newly validated case without modifying design, power or models.

    Placements map die ID to x/y and optional rotation_deg. Every link needs an
    independent package-coordinate horizontal corridor. Reroute after moving.
    Corridors describe ideal conductors, without obstacles, crossings or DRC.
    """
    raw = copy.deepcopy(design.input_data)
    die_ids = {d.id for d in design.dies}
    if set(placements_mm) - die_ids:
        raise ModelError("unknown placement die")
    if set(corridors_y_mm) != {link["id"] for link in design.links}:
        raise ModelError("every link requires an explicit corridor")
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
    placed = parse_case(raw)
    dies = {d.id: d for d in placed.dies}
    for link in raw["links"]:
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
        link["route_points_mm"] = route
    return parse_case(raw)


def evaluate_layout(case):
    """In-memory thermal and route evaluation, with explicit missing timing."""
    power, blocks = rasterize(case)
    temperature, thermal = solve_steady(case, power)
    return dict(
        temperature_c=temperature,
        thermal=thermal,
        blocks=blocks,
        links=estimate_links(case),
        timing_status="not_evaluated",
        complete_package_signoff=False,
    )
