"""Geometric lower bounds only: no routing, extraction, or timing analysis."""


def estimate_links(case):
    cfg = case.interconnect
    if cfg["model"] == "rectangular_wire_parallel_plate":
        r_per_mm = cfg["resistivity_ohm_m"] * 1e-3 / (cfg["width_um"] * cfg["thickness_um"] * 1e-12)
        c_per_mm = 8.8541878128e-12 * cfg["relative_permittivity"] * cfg["width_um"] / cfg["dielectric_height_um"] * 1e9
    else:
        r_per_mm, c_per_mm = cfg["r_ohm_per_mm"], cfg["c_pf_per_mm"]
    dies = {d.id: d for d in case.dies}
    records = []
    for link in case.links:
        points = []
        for endpoint in (link["source"], link["target"]):
            die = dies[endpoint["chiplet"]]
            points.append(die.point(*die.ports[endpoint["port"]]))
        length = sum(abs(a - b) for a, b in zip(*points))
        records.append({"id": link["id"], "kind": link["kind"],
                        "source_mm": points[0], "target_mm": points[1],
                        "manhattan_length_mm": length,
                        "assumed_r_ohm": length * r_per_mm,
                        "assumed_c_pf": length * c_per_mm,
                        "model": case.interconnect["model"],
                        "provenance": case.interconnect["provenance"]})
    return records
