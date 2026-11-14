"""Vectorized rigid-body geometry and source-pin Manhattan length."""
import numpy as np


def rotate(offset_um, rotation_deg):
    """Rotate (..., 2) offsets counterclockwise by matching quarter turns."""
    x, y = offset_um[..., 0], offset_um[..., 1]
    turns = (np.asarray(rotation_deg) // 90) % 4
    rx = np.choose(turns, (x, -y, -x, y))
    ry = np.choose(turns, (y, x, -y, -x))
    return np.stack((rx, ry), axis=-1)


def boxes(problem, layout):
    """(n, 4) rotated bounding boxes [x0, y0, x1, y1] in um."""
    size = np.where((layout.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
    return np.concatenate((layout.centre_um - size/2, layout.centre_um + size/2), axis=1)


def violations(problem, layout, gap_um):
    """Out-of-carrier chiplets and pairs closer than gap_um; touching at gap is legal."""
    if not np.isfinite(gap_um) or gap_um < 0:
        raise ValueError("invalid minimum gap")
    b = boxes(problem, layout)
    width, height = problem.carrier_um
    outside = np.flatnonzero((b[:, 0] < 0) | (b[:, 1] < 0) | (b[:, 2] > width) | (b[:, 3] > height))
    i, j = np.triu_indices(problem.count, 1)
    separated = ((b[i, 2] + gap_um <= b[j, 0]) | (b[j, 2] + gap_um <= b[i, 0])
                 | (b[i, 3] + gap_um <= b[j, 1]) | (b[j, 3] + gap_um <= b[i, 1]))
    return dict(outside=[problem.names[k] for k in outside],
                pairs=[(problem.names[a], problem.names[c]) for a, c in zip(i[~separated], j[~separated])])


def is_legal(problem, layout, gap_um):
    v = violations(problem, layout, gap_um)
    return not v["outside"] and not v["pairs"]


def pin_points_um(problem, layout):
    """(m, 2, 2) world coordinates of every net endpoint."""
    chip = problem.pin_chip
    return layout.centre_um[chip] + rotate(problem.pin_offset_um, layout.rotation_deg[chip])


def pin_manhattan_um(problem, layout):
    """Per-net two-pin Manhattan lower bound (no detours, capacity, RC or timing)."""
    p = pin_points_um(problem, layout)
    return np.abs(p[:, 0] - p[:, 1]).sum(axis=1)


def centre_manhattan_um(problem, layout):
    c = layout.centre_um[problem.pin_chip]
    return np.abs(c[:, 0] - c[:, 1]).sum(axis=1)
