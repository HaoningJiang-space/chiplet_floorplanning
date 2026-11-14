"""Declared TAP-family FV package for imported cases, solved with scipy.

This is the same material recipe as tools/atplace_pin_geometry.make_thermal_case:
fixed 100 mm spreader, 200 mm sink, top Robin h and adiabatic sides/bottom.
It is a research adaptation, not ATPlace's native model or a measured package.
Ports are omitted because they do not enter the mesh, materials or power map.
"""
import numpy as np
from scipy.sparse.linalg import spsolve

from ..model import parse_case
from ..package import assemble_package
from ..power import rasterize
from .geometry import boxes, violations

AMBIENT_C = 45.0
PROVENANCE = ("ATPlace source geometry/power/pins; declared TAP-family FV materials, "
              "fixed 100/200 mm spreader/sink; not native ATPlace or measured calibration")


def _mixture(diameter, pitch, background):
    return 400*(diameter/pitch)**2 + background*(1 - (diameter/pitch)**2)


def thermal_case_data(problem, layout, gap_um, resolution=64):
    v = violations(problem, layout, gap_um)
    if v["outside"] or v["pairs"]:
        raise ValueError(f"illegal layout: {v}")
    width, height = (s/1000 for s in problem.carrier_um)
    if max(width, height) > 100:
        raise ValueError("source carrier exceeds this declared common spreader")
    ox, oy = (200 - width)/2, (200 - height)/2
    b = boxes(problem, layout)
    chips = []
    for k, name in enumerate(problem.names):
        w, h = problem.size_um[k]/1000
        chips.append(dict(id=name, size_mm=dict(width=w, height=h),
                          placement_mm=dict(x=ox + b[k, 0]/1000, y=oy + b[k, 1]/1000),
                          rotation_deg=int(layout.rotation_deg[k]), ports_mm={},
                          blocks=[dict(id="core", rect_mm=dict(x=0, y=0, width=w, height=h),
                                       power_w=float(problem.power_w[k]), provenance=PROVENANCE)]))

    def layer(name, thickness, conductivity, w=width, h=height, die_k=None):
        item = dict(id=name, thickness_mm=thickness, conductivity_w_mk=conductivity,
                    footprint="rectangle", rect_mm=dict(x=(200 - w)/2, y=(200 - h)/2, width=w, height=h))
        if die_k is not None:
            item["die_materials"] = {c["id"]: dict(conductivity_w_mk=die_k) for c in chips}
        return item

    layers = [layer("substrate", .2, 1/3.33), layer("c4", .07, _mixture(250, 600, 1.6)),
              layer("interposer", .11, _mixture(10, 50, 100)),
              layer("microbumps", .01, 1.6, die_k=_mixture(25, 45, 1.6)),
              layer("dies", .15, 1.6, die_k=100), layer("tim", .02, 4),
              layer("spreader", 1, 400, 100, 100), layer("sink", 6.9, 400, 200, 200)]
    return dict(schema_version=1, name="atplace_fv_" + problem.name,
                package_mm=dict(width=200, height=200),
                grid=dict(nx=resolution, ny=resolution, mode="geometry_conformal"), chiplets=chips,
                thermal=dict(model="layered_package_steady", ambient_c=AMBIENT_C, top_h_w_m2k=1/(.1*.06**2),
                             bottom_h_w_m2k=0, power_layer="dies", provenance=PROVENANCE, layers=layers),
                interconnect=dict(model="manhattan_lower_bound", r_ohm_per_mm=0, c_pf_per_mm=0,
                                  provenance="unused; source pins are evaluated separately"),
                links=[])


def solve(data):
    """Steady solve; power-layer peak (degC), energy-balance bookkeeping and the
    power-layer rise field (K) on mesh cells, with cell edges in package mm."""
    case = parse_case(data)
    power, _ = rasterize(case)
    a, b, g, _, ids, power_z = assemble_package(case, power)
    theta = spsolve(a.tocsc(), b)
    removed = float(g @ theta)
    layer = ids[power_z]
    rise = np.where(layer >= 0, theta[np.maximum(layer, 0)], np.nan)
    summary = dict(peak_power_layer_c=float(np.nanmax(rise) + case.thermal["ambient_c"]),
                   source_power_w=float(b.sum()), heat_removed_w=removed,
                   energy_balance_error_w=removed - float(b.sum()), min_rise_k=float(theta.min()),
                   physical_calibrated=False)
    edges = (np.concatenate(([0], np.cumsum(case.mesh.widths_mm))),
             np.concatenate(([0], np.cumsum(case.mesh.heights_mm))))
    return summary, rise, edges


def solve_peak(data):
    return solve(data)[0]
