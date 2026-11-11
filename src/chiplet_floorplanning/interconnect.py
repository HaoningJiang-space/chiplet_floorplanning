"""Geometric lower bounds only: no routing, extraction, or timing analysis."""


def estimate_links(case):
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
                        "assumed_r_ohm": length * case.interconnect["r_ohm_per_mm"],
                        "assumed_c_pf": length * case.interconnect["c_pf_per_mm"],
                        "model": case.interconnect["model"],
                        "provenance": case.interconnect["provenance"]})
    return records
