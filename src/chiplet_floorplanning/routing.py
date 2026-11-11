"""Finite-width routing on one declared planar layer, not package/PDK signoff.

Die bodies above the routing layer are not metal keepouts. Obstacles must be
declared explicitly. Square trace envelopes use conservative L-infinity
spacing near corners. No vias, crossovers, bump escape, coupling or extraction.
"""

import copy
from dataclasses import dataclass
import heapq
import itertools

from .model import ModelError, Rect, fields, number, parse_case, parse_rect, text

EPS_MM = 1e-10


@dataclass(frozen=True)
class PlanarRules:
    trace_width_um: float
    spacing_um: float
    edge_clearance_um: float
    keepouts_mm: tuple
    provenance: str

    def __post_init__(self):
        for name in ("trace_width_um", "spacing_um", "edge_clearance_um"):
            number(getattr(self, name), name, positive=True)
        if not all(
            isinstance(r, Rect) and r.width > 0 and r.height > 0
            for r in self.keepouts_mm
        ):
            raise ModelError("invalid routing keepout rectangles")
        text(self.provenance, "routing provenance")

    @classmethod
    def from_dict(cls, raw):
        fields(
            raw,
            (
                "trace_width_um",
                "spacing_um",
                "edge_clearance_um",
                "keepouts_mm",
                "provenance",
            ),
        )
        if not isinstance(raw["keepouts_mm"], list):
            raise ModelError("routing keepouts must be a list")
        return cls(
            **{**raw, "keepouts_mm": tuple(parse_rect(r) for r in raw["keepouts_mm"])}
        )

    @property
    def separation_mm(self):
        return (self.trace_width_um + self.spacing_um) / 1000

    @property
    def margin_mm(self):
        return (self.trace_width_um / 2 + self.edge_clearance_um) / 1000


def endpoints(case):
    dies = {d.id: d for d in case.dies}
    return {
        link["id"]: tuple(
            dies[e["chiplet"]].point(*dies[e["chiplet"]].ports[e["port"]])
            for e in (link["source"], link["target"])
        )
        for link in case.links
    }


def segments(route):
    return list(zip(route, route[1:]))


def route_length_mm(route):
    return sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in segments(route))


def envelope(segment, padding):
    a, b = segment
    return (
        min(a[0], b[0]) - padding,
        min(a[1], b[1]) - padding,
        max(a[0], b[0]) + padding,
        max(a[1], b[1]) + padding,
    )


def intersects_open_box(segment, box):
    a, b = segment
    x0, y0, x1, y1 = box
    if abs(a[1] - b[1]) < EPS_MM:
        return (
            y0 + EPS_MM < a[1] < y1 - EPS_MM
            and max(a[0], b[0]) > x0 + EPS_MM
            and min(a[0], b[0]) < x1 - EPS_MM
        )
    if abs(a[0] - b[0]) < EPS_MM:
        return (
            x0 + EPS_MM < a[0] < x1 - EPS_MM
            and max(a[1], b[1]) > y0 + EPS_MM
            and min(a[1], b[1]) < y1 - EPS_MM
        )
    raise ModelError("routing segment is not rectilinear")


def segment_distance_mm(a, b):
    a0, a1, a2, a3 = envelope(a, 0)
    b0, b1, b2, b3 = envelope(b, 0)
    return max(0.0, a0 - b2, b0 - a2, a1 - b3, b1 - a3)


def _keepout_boxes(case, rules):
    if any(not case.package.contains(r) for r in rules.keepouts_mm):
        raise ModelError("routing keepout outside package")
    if (
        "width_um" in case.interconnect
        and case.interconnect["width_um"] != rules.trace_width_um
    ):
        raise ModelError("routing width differs from electrical wire width")
    padding = (rules.trace_width_um / 2 + rules.spacing_um) / 1000
    return [
        (
            r.x - padding,
            r.y - padding,
            r.x + r.width + padding,
            r.y + r.height + padding,
        )
        for r in rules.keepouts_mm
    ]


def audit_routes(case, rules):
    """Check the declared single-layer conductor geometry, including shorts."""
    boxes = _keepout_boxes(case, rules)
    issues, routes = [], {}
    margin = rules.margin_mm
    for link in case.links:
        name, route = link["id"], link.get("route_points_mm")
        if not route:
            issues.append(f"{name}: explicit route required; Manhattan is not routing")
            continue
        routes[name] = route
        if any(
            not (
                margin - EPS_MM <= p[0] <= case.package.width - margin + EPS_MM
                and margin - EPS_MM <= p[1] <= case.package.height - margin + EPS_MM
            )
            for p in route
        ):
            issues.append(f"{name}: finite-width trace violates package edge clearance")
        ss = segments(route)
        if any(intersects_open_box(s, box) for s in ss for box in boxes):
            issues.append(f"{name}: trace violates explicit keepout clearance")
        if len(set(map(tuple, route))) != len(route):
            issues.append(f"{name}: repeated route vertex")
        for i, (a, b) in enumerate(ss):
            if i + 1 < len(ss):
                c = ss[i + 1][1]
                if (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (
                    c[1] - b[1]
                ) < -EPS_MM:
                    issues.append(f"{name}: adjacent segments backtrack")
            for j in range(i + 2, len(ss)):
                if segment_distance_mm(ss[i], ss[j]) < rules.separation_mm - EPS_MM:
                    issues.append(
                        f"{name}: nonadjacent segments violate self clearance"
                    )
    min_spacing = None
    for a, b in itertools.combinations(routes, 2):
        distance = min(
            segment_distance_mm(s, t)
            for s in segments(routes[a])
            for t in segments(routes[b])
        )
        edge_spacing = distance - rules.trace_width_um / 1000
        min_spacing = (
            edge_spacing if min_spacing is None else min(min_spacing, edge_spacing)
        )
        if distance < rules.separation_mm - EPS_MM:
            issues.append(f"{a}/{b}: same-layer crossing, short or spacing violation")
    return dict(
        geometry_legal=not issues,
        issues=issues,
        signal_layer_count=1,
        via_count=0,
        minimum_inter_net_edge_spacing_mm=min_spacing,
        scope="declared_planar_wire_geometry_only_not_bump_escape_PDK_DRC_or_SI",
        under_die_routing="allowed_on_interposer_layer; die bodies are not metal keepouts",
        complete_package_signoff=False,
    )


def with_routes(case, routes, *, timings_s=None):
    if set(routes) != {link["id"] for link in case.links}:
        raise ModelError("route IDs differ from case links")
    raw = copy.deepcopy(case.input_data)
    for link in raw["links"]:
        link["route_points_mm"] = [list(p) for p in routes[link["id"]]]
    return parse_case(raw, timings_s=timings_s)


def _compress(points):
    out = []
    for p in points:
        if len(out) >= 2 and (
            (out[-2][0] == out[-1][0] == p[0]) or (out[-2][1] == out[-1][1] == p[1])
        ):
            out.pop()
        out.append(p)
    return out


def shortest_path(start, end, width_mm, height_mm, margin_mm, boxes):
    """Shortest grid path; fewest bends breaks equal-length ties."""
    start, end = [tuple(round(v, 12) for v in p) for p in (start, end)]
    xs = {start[0], end[0], margin_mm, width_mm - margin_mm}
    ys = {start[1], end[1], margin_mm, height_mm - margin_mm}
    for x0, y0, x1, y1 in boxes:
        xs.update((x0, x1))
        ys.update((y0, y1))
    xs = sorted(
        {
            round(x, 12)
            for x in xs
            if margin_mm - EPS_MM <= x <= width_mm - margin_mm + EPS_MM
        }
    )
    ys = sorted(
        {
            round(y, 12)
            for y in ys
            if margin_mm - EPS_MM <= y <= height_mm - margin_mm + EPS_MM
        }
    )
    if len(xs) * len(ys) > 25000:
        raise ModelError("routing visibility grid exceeds 25000 vertices")
    if any(p[0] not in xs or p[1] not in ys for p in (start, end)):
        return None
    source, target = (xs.index(start[0]), ys.index(start[1])), (
        xs.index(end[0]),
        ys.index(end[1]),
    )

    def allowed(p):
        return not any(
            x0 + EPS_MM < p[0] < x1 - EPS_MM and y0 + EPS_MM < p[1] < y1 - EPS_MM
            for x0, y0, x1, y1 in boxes
        )

    if not allowed(start) or not allowed(end):
        return None
    initial = (*source, 2)
    distance, parent, queue = {initial: (0.0, 0)}, {}, [(0.0, 0, initial)]
    while queue:
        cost, bends, node = heapq.heappop(queue)
        if (cost, bends) != distance[node]:
            continue
        if node[:2] == target:
            path = [node]
            while path[-1] != initial:
                path.append(parent[path[-1]])
            return _compress([(xs[x], ys[y]) for x, y, _ in reversed(path)])
        x, y, direction = node
        a = (xs[x], ys[y])
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if not (0 <= nx < len(xs) and 0 <= ny < len(ys)):
                continue
            b = (xs[nx], ys[ny])
            if not allowed(b) or any(intersects_open_box((a, b), box) for box in boxes):
                continue
            new_direction = 0 if nx != x else 1
            state = (nx, ny, new_direction)
            candidate = (
                round(cost + abs(a[0] - b[0]) + abs(a[1] - b[1]), 12),
                bends + int(direction != 2 and direction != new_direction),
            )
            if candidate < distance.get(state, (float("inf"), 0)):
                distance[state], parent[state] = candidate, node
                heapq.heappush(queue, (*candidate, state))
    return None


def shortest_route_pairs(case, rules):
    """Try both net orders; no claim of global two-net optimality."""
    ends = endpoints(case)
    if len(ends) != 2:
        raise ModelError("paired router requires exactly two nets")
    base_boxes, candidates = _keepout_boxes(case, rules), []
    for order in itertools.permutations(sorted(ends)):
        routes = {}
        for name in order:
            boxes = list(base_boxes)
            for other, terminals in ends.items():
                if other != name:
                    boxes += [envelope((p, p), rules.separation_mm) for p in terminals]
            for existing in routes.values():
                boxes += [envelope(s, rules.separation_mm) for s in segments(existing)]
            path = shortest_path(
                *ends[name],
                case.package.width,
                case.package.height,
                rules.margin_mm,
                boxes,
            )
            if path is None:
                break
            routes[name] = path
        if len(routes) == len(ends):
            routed = with_routes(case, routes)
            audit = audit_routes(routed, rules)
            if audit["geometry_legal"]:
                candidates.append(
                    dict(
                        routes=routes,
                        routing_order=list(order),
                        length_mm=sum(route_length_mm(p) for p in routes.values()),
                        audit=audit,
                    )
                )
    return sorted(candidates, key=lambda c: (c["length_mm"], c["routing_order"]))
