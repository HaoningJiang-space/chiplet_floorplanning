"""Input contract and rigid geometry transforms (millimetres, watts)."""

from dataclasses import dataclass
import math
from pathlib import Path
import json
import re
from time import perf_counter

from .mesh import ThermalMesh, make_mesh


class ModelError(ValueError):
    """Invalid or unsupported evaluation input."""


def fields(value, required, optional=()):
    if not isinstance(value, dict):
        raise ModelError("expected an object")
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing or unknown:
        raise ModelError(f"missing fields: {sorted(missing)}; unknown fields: {sorted(unknown)}")


def number(value, label, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ModelError(f"{label}: expected a finite number")
    if (minimum is not None and value < minimum) or (positive and value <= 0):
        raise ModelError(f"{label}: value out of range")
    return float(value)


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"{label}: expected nonempty text")
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
        raise ModelError("IDs must match [A-Za-z][A-Za-z0-9_]*")
    return value


def sequence(value, label, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        raise ModelError(f"{label}: expected {'nonempty ' if nonempty else ''}list")
    return value


def unique(values, label):
    if len(values) != len(set(values)):
        raise ModelError(f"duplicate {label}")


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def area(self):
        return self.width * self.height

    def overlap(self, other):
        width = max(0.0, min(self.x + self.width, other.x + other.width) - max(self.x, other.x))
        height = max(0.0, min(self.y + self.height, other.y + other.height) - max(self.y, other.y))
        return width * height

    def contains(self, other):
        return (self.x <= other.x and self.y <= other.y
                and other.x + other.width <= self.x + self.width
                and other.y + other.height <= self.y + self.height)


def parse_rect(value):
    fields(value, ("x", "y", "width", "height"))
    return Rect(number(value["x"], "x", minimum=0), number(value["y"], "y", minimum=0),
                number(value["width"], "width", positive=True),
                number(value["height"], "height", positive=True))


@dataclass(frozen=True)
class Block:
    id: str
    rect: Rect
    power_w: float
    provenance: str


@dataclass(frozen=True)
class Die:
    id: str
    width: float
    height: float
    x: float
    y: float
    rotation: int
    blocks: tuple
    ports: dict

    def point(self, x, y):
        """Rotate CCW, then translate the rotated bounding box's lower left."""
        if self.rotation == 90:
            x, y = self.height - y, x
        elif self.rotation == 180:
            x, y = self.width - x, self.height - y
        elif self.rotation == 270:
            x, y = y, self.width - x
        return self.x + x, self.y + y

    def transform(self, rect):
        corners = [self.point(x, y) for x in (rect.x, rect.x + rect.width)
                   for y in (rect.y, rect.y + rect.height)]
        xs, ys = zip(*corners)
        return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    @property
    def bounds(self):
        return self.transform(Rect(0, 0, self.width, self.height))


@dataclass(frozen=True)
class Case:
    name: str
    package: Rect
    mesh: ThermalMesh
    dies: tuple
    thermal: dict
    interconnect: dict
    links: tuple
    input_data: dict

    @property
    def nx(self):
        return self.mesh.nx

    @property
    def ny(self):
        return self.mesh.ny


def parse_case(data, *, timings_s=None):
    started = perf_counter()
    fields(data, ("schema_version", "name", "package_mm", "grid", "chiplets", "thermal", "interconnect", "links"))
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ModelError("schema_version must be integer 1")
    name = identifier(data["name"])
    package = data["package_mm"]
    fields(package, ("width", "height"))
    package = parse_rect(dict(package, x=0, y=0))
    grid = data["grid"]
    fields(grid, ("nx", "ny"), ('mode',))
    if any(type(grid[key]) is not int or grid[key] < 1 for key in ("nx", "ny")):
        raise ModelError("grid dimensions must be positive integers")
    if grid["nx"] * grid["ny"] > 250_000:
        raise ModelError("grid exceeds the prototype limit of 250000 cells")
    dies = []
    for raw in sequence(data["chiplets"], "chiplets", nonempty=True):
        fields(raw, ("id", "size_mm", "placement_mm", "rotation_deg", "blocks", "ports_mm"))
        fields(raw["size_mm"], ("width", "height"))
        local = parse_rect(dict(raw["size_mm"], x=0, y=0))
        fields(raw["placement_mm"], ("x", "y"))
        x = number(raw["placement_mm"]["x"], "placement x", minimum=0)
        y = number(raw["placement_mm"]["y"], "placement y", minimum=0)
        rotation = raw["rotation_deg"]
        if type(rotation) is not int or rotation not in (0, 90, 180, 270):
            raise ModelError("rotation_deg must be 0, 90, 180, or 270")
        blocks = []
        for block in sequence(raw["blocks"], "blocks", nonempty=True):
            fields(block, ("id", "rect_mm", "power_w", "provenance"))
            b = Block(identifier(block["id"]), parse_rect(block["rect_mm"]),
                      number(block["power_w"], "power_w", minimum=0),
                      text(block["provenance"], "power provenance"))
            if not local.contains(b.rect):
                raise ModelError(f"block {b.id} outside chiplet")
            if any(b.rect.overlap(previous.rect) > 0 for previous in blocks):
                raise ModelError(f"overlapping power block {b.id}")
            blocks.append(b)
        unique([b.id for b in blocks], "block IDs")
        if not isinstance(raw["ports_mm"], dict):
            raise ModelError("ports_mm must be an object")
        ports = {}
        for key, value in raw["ports_mm"].items():
            identifier(key)
            fields(value, ("x", "y"))
            px = number(value["x"], "port x", minimum=0)
            py = number(value["y"], "port y", minimum=0)
            if px > local.width or py > local.height:
                raise ModelError(f"port {key} outside chiplet")
            ports[key] = (px, py)
        die = Die(identifier(raw["id"]), local.width, local.height, x, y, rotation, tuple(blocks), ports)
        if not package.contains(die.bounds):
            raise ModelError(f"chiplet {die.id} outside package")
        if any(die.bounds.overlap(previous.bounds) > 0 for previous in dies):
            raise ModelError(f"overlapping chiplet {die.id}")
        dies.append(die)
    unique([d.id for d in dies], "chiplet IDs")
    thermal = dict(data["thermal"]) if isinstance(data["thermal"], dict) else data["thermal"]
    if isinstance(thermal, dict) and thermal.get("model") == "layered_package_steady":
        fields(thermal, ("model", "layers", "power_layer", "top_h_w_m2k", "bottom_h_w_m2k", "ambient_c", "provenance"))
        layers = sequence(thermal["layers"], "layers", nonempty=True)
        for layer in layers:
            fields(layer, ("id", "footprint", "thickness_mm"),
                   ('conductivity_w_mk', 'conductivity_xyz_w_mk', 'contact_resistance_above_m2k_w',
                    'rect_mm', 'die_materials', 'sidewall_contacts'))
            identifier(layer["id"])
            if layer["footprint"] not in ("package", "chiplets", "rectangle"):
                raise ModelError("layer footprint must be package, chiplets or rectangle")
            if layer['footprint'] == 'rectangle':
                if 'rect_mm' not in layer or not package.contains(parse_rect(layer['rect_mm'])):
                    raise ModelError('rectangle layer needs rect_mm inside package')
            elif 'rect_mm' in layer:
                raise ModelError('rect_mm requires rectangle footprint')
            number(layer['thickness_mm'], 'thickness_mm', positive=True)
            if ('conductivity_w_mk' in layer) == ('conductivity_xyz_w_mk' in layer):
                raise ModelError('specify exactly one scalar or xyz conductivity')
            if 'conductivity_w_mk' in layer:
                number(layer['conductivity_w_mk'], 'conductivity_w_mk', positive=True)
            else:
                components = sequence(layer['conductivity_xyz_w_mk'], 'conductivity_xyz_w_mk')
                if len(components) != 3:
                    raise ModelError('conductivity_xyz_w_mk requires x, y, z components')
                for value in components:
                    number(value, 'conductivity_xyz_w_mk', positive=True)
            number(layer.get('contact_resistance_above_m2k_w', 0), 'contact_resistance_above_m2k_w', minimum=0)
            materials = layer.get('die_materials', {})
            if not isinstance(materials, dict) or materials.keys()-{d.id for d in dies}:
                raise ModelError('unknown die material assignment')
            for material in materials.values():
                fields(material, (), ('conductivity_w_mk', 'conductivity_xyz_w_mk'))
                if len(material) != 1:
                    raise ModelError('die material requires one scalar or xyz conductivity')
                values = ([material['conductivity_w_mk']] if 'conductivity_w_mk' in material
                          else sequence(material['conductivity_xyz_w_mk'], 'conductivity_xyz_w_mk'))
                if 'conductivity_xyz_w_mk' in material and len(values) != 3:
                    raise ModelError('die conductivity requires three package-axis components')
                for value in values:
                    number(value, 'die conductivity_w_mk', positive=True)
            contacts = sequence(layer.get('sidewall_contacts', []), 'sidewall_contacts')
            pairs = []
            for contact in contacts:
                fields(contact, ('dies', 'resistance_m2k_w'))
                pair = [identifier(name) for name in sequence(contact['dies'], 'sidewall dies')]
                if len(pair) != 2 or len(set(pair)) != 2 or set(pair)-{d.id for d in dies}:
                    raise ModelError('sidewall contact requires two distinct known dies')
                rects = [next(d.bounds for d in dies if d.id == name) for name in pair]
                a, b = rects
                vertical = (math.isclose(a.x+a.width, b.x, rel_tol=0, abs_tol=1e-12)
                            or math.isclose(b.x+b.width, a.x, rel_tol=0, abs_tol=1e-12))
                horizontal = (math.isclose(a.y+a.height, b.y, rel_tol=0, abs_tol=1e-12)
                              or math.isclose(b.y+b.height, a.y, rel_tol=0, abs_tol=1e-12))
                if not ((vertical and min(a.y+a.height, b.y+b.height) > max(a.y, b.y))
                        or (horizontal and min(a.x+a.width, b.x+b.width) > max(a.x, b.x))):
                    raise ModelError('sidewall contact cannot bridge a gap or a point contact')
                number(contact['resistance_m2k_w'], 'sidewall resistance_m2k_w', minimum=0)
                pairs.append(tuple(sorted(pair)))
            unique(pairs, 'sidewall contacts')
            if (materials or contacts) and layer['footprint'] != 'chiplets':
                raise ModelError('die materials and sidewall contacts require chiplets footprint')
        if layers[-1].get('contact_resistance_above_m2k_w', 0) != 0:
            raise ModelError('contact resistance above final layer has no material interface')
        unique([layer["id"] for layer in layers], "layer IDs")
        if thermal["power_layer"] not in [layer["id"] for layer in layers]:
            raise ModelError("unknown power_layer")
        for key in ("top_h_w_m2k", "bottom_h_w_m2k"):
            number(thermal[key], key, minimum=0)
        if thermal["top_h_w_m2k"] + thermal["bottom_h_w_m2k"] <= 0:
            raise ModelError("package needs at least one positive convection boundary")
        if len(layers) * grid["nx"] * grid["ny"] > 250_000:
            raise ModelError("package exceeds 250000 potential nodes")
    else:
        fields(thermal, ("model", "conductivity_w_mk", "thickness_mm", "sink_h_w_m2k", "ambient_c", "provenance"))
        if thermal["model"] != "uniform_slab_steady":
            raise ModelError("unknown thermal model")
        for key in ("conductivity_w_mk", "thickness_mm", "sink_h_w_m2k"):
            thermal[key] = number(thermal[key], key, positive=True)
    thermal["ambient_c"] = number(thermal["ambient_c"], "ambient_c", minimum=-273.15)
    text(thermal["provenance"], "thermal provenance")
    interconnect = data["interconnect"]
    if isinstance(interconnect, dict) and interconnect.get("model") == "rectangular_wire_parallel_plate":
        parameters = ("resistivity_ohm_m", "width_um", "thickness_um", "dielectric_height_um", "relative_permittivity")
        fields(interconnect, ("model", "provenance", *parameters))
        for key in parameters:
            number(interconnect[key], key, positive=True)
    else:
        fields(interconnect, ("model", "r_ohm_per_mm", "c_pf_per_mm", "provenance"))
        if interconnect["model"] != "manhattan_lower_bound":
            raise ModelError("unknown interconnect model")
        for key in ("r_ohm_per_mm", "c_pf_per_mm"):
            number(interconnect[key], key, minimum=0)
    text(interconnect["provenance"], "interconnect provenance")
    links = sequence(data["links"], "links")
    by_id = {d.id: d for d in dies}
    for link in links:
        fields(link, ("id", "kind", "source", "target"), ('route_points_mm',))
        identifier(link["id"])
        if link["kind"] not in ("data", "clock"):
            raise ModelError("link kind must be data or clock")
        for endpoint in (link["source"], link["target"]):
            fields(endpoint, ("chiplet", "port"))
            die_id, port = identifier(endpoint["chiplet"]), identifier(endpoint["port"])
            if die_id not in by_id or port not in by_id[die_id].ports:
                raise ModelError(f"unknown endpoint {die_id}/{port}")
        if link["source"]["chiplet"] == link["target"]["chiplet"]:
            raise ModelError("links must cross chiplets")
        if 'route_points_mm' in link:
            route = sequence(link['route_points_mm'], 'route_points_mm', nonempty=True)
            if not 2 <= len(route) <= 10000:
                raise ModelError('route needs 2 to 10000 points')
            for point in route:
                if not isinstance(point, list) or len(point) != 2:
                    raise ModelError('route points require package x,y in mm')
                x, y = [number(v, 'route coordinate_mm', minimum=0) for v in point]
                if x > package.width or y > package.height:
                    raise ModelError('route outside package')
            for a, b in zip(route, route[1:]):
                if (a[0] == b[0]) == (a[1] == b[1]):
                    raise ModelError('route segments must be nonzero and axis aligned')
            for point, endpoint in zip((route[0], route[-1]), (link['source'], link['target'])):
                die = by_id[endpoint['chiplet']]
                expected = die.point(*die.ports[endpoint['port']])
                if any(not math.isclose(a, b, rel_tol=0, abs_tol=1e-10) for a, b in zip(point, expected)):
                    raise ModelError('route endpoint differs from transformed chiplet port; reroute after moving die')
    unique([link["id"] for link in links], "link IDs")
    mode = grid.get('mode', 'geometry_conformal' if thermal['model'] == 'layered_package_steady' else 'uniform')
    rectangles = [r for die in dies for r in [die.bounds]+[die.transform(b.rect) for b in die.blocks]]
    rectangles += [parse_rect(layer['rect_mm']) for layer in thermal.get('layers', [])
                   if layer['footprint'] == 'rectangle']
    mesh_started = perf_counter()
    try:
        mesh = make_mesh(package.width, package.height, grid['nx'], grid['ny'], mode, rectangles)
    except ValueError as error:
        raise ModelError(str(error)) from error
    if mesh.nx*mesh.ny*len(thermal.get('layers', [None])) > 250_000:
        raise ModelError('geometry-conforming mesh exceeds 250000 potential nodes')
    if timings_s is not None:
        timings_s['mesh_generation_s'] = perf_counter() - mesh_started
        timings_s['input_validation_s'] = mesh_started - started
    return Case(name, package, mesh, tuple(dies), thermal, interconnect, tuple(links), data)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_case(path):
    return parse_case(json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_object))
