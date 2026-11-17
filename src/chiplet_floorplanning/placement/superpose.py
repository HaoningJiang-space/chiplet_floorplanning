"""Thermal model by superposing single-die FV fields (plan: docs/superposition-model-plan.md).

Steady conduction with convective boundaries is linear, T = T_amb + G P. If the bodies of the other dies and the
carrier edges did not change the heat paths, G would depend only on displacements: the rise at r caused by die j is
P_j F_s(R_j^-1 (r - c_j)), with F_s the power-layer rise field of a lone 1 W die of size s. F_s comes from one FV
solve per distinct die size, on a carrier enlarged so that the field covers every displacement, with the real
package's spreader. There are no fitted parameters; the neglected terms are what validation measures.
"""
from dataclasses import dataclass, replace

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from ..model import parse_case
from ..package import assemble_package, solve_spd
from ..power import rasterize
from .problem import Layout, Problem
from .thermal import AMBIENT_C, PACKAGE_MM, thermal_case_data

SAMPLE_MM = 0.5
ENLARGE = 2.0


def spreader_of(problem):
    return max(100.0, max(problem.carrier_um)/1000 + 20)


def lone_field(problem, size_um, resolution=64):
    """(x mm, y mm, rise K/W) of the power layer around a lone 1 W die of size_um at the centre of an enlarged
    carrier, coordinates relative to the die centre."""
    side = min(ENLARGE*max(problem.carrier_um)/1000, PACKAGE_MM - 20)
    alone = Problem('lone', ('die',), np.array([size_um], float), np.ones(1), (side*1000, side*1000),
                    np.zeros((0, 2), int), np.zeros((0, 2, 2)), problem.top_h_w_m2k)
    data = thermal_case_data(alone, Layout(np.array([[side*500, side*500]]), np.zeros(1, int)), 0.0, resolution,
                             spreader_mm=spreader_of(problem))
    case = parse_case(data)
    power, _ = rasterize(case)
    a, b, _, _, ids, power_z = assemble_package(case, power)
    theta = solve_spd(a, b)
    layer = ids[power_z]
    xe = np.concatenate(([0], np.cumsum(case.mesh.widths_mm)))
    ye = np.concatenate(([0], np.cumsum(case.mesh.heights_mm)))
    xc, yc = (xe[:-1] + xe[1:])/2 - PACKAGE_MM/2, (ye[:-1] + ye[1:])/2 - PACKAGE_MM/2
    rows, cols = np.flatnonzero((layer >= 0).any(axis=1)), np.flatnonzero((layer >= 0).any(axis=0))
    field = theta[layer[np.ix_(rows, cols)]]
    return xc[cols], yc[rows], field


@dataclass
class SuperposedModel:
    fields: dict            # size key (w_um, h_um) -> RegularGridInterpolator over (y, x) mm, die frame
    solves: int

    @classmethod
    def calibrate(cls, problem, resolution=64):
        fields = {}
        for size in {tuple(s) for s in problem.size_um}:
            x, y, f = lone_field(problem, size, resolution)
            fields[size] = RegularGridInterpolator((y, x), f, bounds_error=False, fill_value=None)
        return cls(fields, len(fields))

    def die_peaks_c(self, problem, layout):
        """Absolute peak (degC) of every die: max over 0.5 mm samples of the superposed rise."""
        size = np.where((layout.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)/1000
        centre = layout.centre_um/1000
        turns = (layout.rotation_deg//90) % 4
        peaks = np.empty(problem.count)
        for i in range(problem.count):
            nx, ny = (max(2, int(np.ceil(v/SAMPLE_MM)) + 1) for v in size[i])
            gx, gy = np.meshgrid(np.linspace(-size[i, 0]/2, size[i, 0]/2, nx), np.linspace(-size[i, 1]/2, size[i, 1]/2, ny))
            points = np.stack((gx.ravel() + centre[i, 0], gy.ravel() + centre[i, 1]), axis=1)
            rise = np.zeros(len(points))
            for j in np.flatnonzero(problem.power_w > 0):
                d = points - centre[j]
                # Field of a die turned by q quarter turns at d equals the unturned field at R^-q d.
                q = turns[j]
                for _ in range(q):
                    d = np.stack((d[:, 1], -d[:, 0]), axis=1)
                rise += problem.power_w[j]*self.fields[tuple(problem.size_um[j])](d[:, ::-1])
            peaks[i] = AMBIENT_C + rise.max()
        return peaks

    def peak_c(self, problem, layout):
        return float(self.die_peaks_c(problem, layout).max())
