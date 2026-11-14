"""Rectilinear thermal geometry in millimetres; geometry is never snapped."""

from dataclasses import dataclass
import math

import numpy as np

# Geometry tolerance (mm). The same physical edge reached by different float
# expressions (e.g. x_a + w_a and x_b for touching dies) differs by ~1e-14 mm;
# features closer than 0.1 pm are numerical noise, not geometry. Matches the
# boundary lookup tolerance in package.rectangle_slice.
GEOMETRY_TOL_MM = 1e-10


@dataclass(frozen=True)
class ThermalMesh:
    x_edges_mm: tuple
    y_edges_mm: tuple
    mode: str
    requested_nx: int
    requested_ny: int

    @property
    def nx(self):
        return len(self.x_edges_mm)-1

    @property
    def ny(self):
        return len(self.y_edges_mm)-1

    @property
    def widths_mm(self):
        return np.diff(self.x_edges_mm)

    @property
    def heights_mm(self):
        return np.diff(self.y_edges_mm)

    @property
    def x_centers_mm(self):
        a = np.asarray(self.x_edges_mm)
        return (a[:-1]+a[1:])/2

    @property
    def y_centers_mm(self):
        a = np.asarray(self.y_edges_mm)
        return (a[:-1]+a[1:])/2

    @property
    def areas_mm2(self):
        return np.outer(self.heights_mm, self.widths_mm)

    def record(self):
        return {'mode': self.mode, 'requested_nx': self.requested_nx, 'requested_ny': self.requested_ny,
                'nx': self.nx, 'ny': self.ny, 'x_edges_mm': list(self.x_edges_mm),
                'y_edges_mm': list(self.y_edges_mm), 'geometry_snapped': False}


def _axis(extent, count, boundaries):
    # Subdivide feature intervals instead of overlaying a fixed grid. This
    # avoids tiny artificial cells when a die edge nearly meets a grid line.
    anchors = []
    for value in sorted([0.0, extent]+[float(x) for x in boundaries]):
        if not anchors or value - anchors[-1] > GEOMETRY_TOL_MM:
            anchors.append(value)
    if anchors[0] < -GEOMETRY_TOL_MM or anchors[-1] > extent + GEOMETRY_TOL_MM:
        raise ValueError('mesh feature outside package')
    anchors[0], anchors[-1] = 0.0, extent
    edges = [anchors[0]]
    target = extent/count
    for left, right in zip(anchors, anchors[1:]):
        span = right-left
        if span <= 32*np.finfo(float).eps*max(1, extent):
            raise ValueError('distinct geometry boundaries are below numerical resolution')
        n = max(1, math.ceil(span/target-1e-12))
        edges.extend(np.linspace(left, right, n+1)[1:].tolist())
    return tuple(edges)


def make_mesh(width_mm, height_mm, nx, ny, mode, rectangles):
    if mode == 'uniform':
        x = tuple(np.linspace(0, width_mm, nx+1))
        y = tuple(np.linspace(0, height_mm, ny+1))
    elif mode == 'geometry_conformal':
        x = _axis(width_mm, nx, [v for r in rectangles for v in (r.x, r.x+r.width)])
        y = _axis(height_mm, ny, [v for r in rectangles for v in (r.y, r.y+r.height)])
    else:
        raise ValueError('mesh mode must be uniform or geometry_conformal')
    return ThermalMesh(x, y, mode, nx, ny)
