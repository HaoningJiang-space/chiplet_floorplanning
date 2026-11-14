"""Legal-move neighbourhoods and exact length descent.

Lower-left corners stay on the grid (default 1 mm). Every proposal is checked
for legality before evaluation; temperatures are exact FV peaks from Evaluator.
"""
import numpy as np

from .geometry import is_legal, pin_manhattan_um, rotate
from .problem import Layout

STEPS_MM = (1, 2, 4, 8)


def rotated_size(problem, rotation):
    return np.where((np.asarray(rotation) % 180 != 0)[..., None], problem.size_um[:, ::-1], problem.size_um)


def snap(problem, centre, rotation, grid_um):
    """Move centres so lower-left corners sit on the grid."""
    half = rotated_size(problem, rotation)/2
    return np.round((centre - half)/grid_um)*grid_um + half


def layout_key(layout):
    return layout.centre_um.round(3).tobytes() + layout.rotation_deg.astype(np.int16).tobytes()


def length_target(problem, layout, k):
    """Exact single-chip minimiser of total pin length: per-axis median of partner pins.

    Nets with both ends on chip k are translation invariant and do not enter the target.
    """
    chip = problem.pin_chip
    rows, side = np.nonzero(chip == k)
    external = chip[rows, 1 - side] != k
    rows, side = rows[external], side[external]
    if not rows.size:
        return layout.centre_um[k]
    other = 1 - side
    partner = (layout.centre_um[chip[rows, other]]
               + rotate(problem.pin_offset_um[rows, other], layout.rotation_deg[chip[rows, other]]))
    own = rotate(problem.pin_offset_um[rows, side], np.full(rows.size, layout.rotation_deg[k]))
    return np.median(partner - own, axis=0)


def mutate(problem, layout, rng, gap_um, grid_um=1000):
    """One random legal move, or None if the drawn move is illegal.

    Only the moved chiplets are snapped to the grid; the others keep their positions.
    """
    centre, rotation = layout.centre_um.copy(), layout.rotation_deg.copy()
    k = int(rng.integers(problem.count))
    moved = [k]
    kind = rng.choice(("shift", "rotate", "swap", "pull"), p=(.45, .15, .15, .25))
    if kind == "shift":
        centre[k, rng.integers(2)] += rng.choice((-1, 1))*rng.choice(STEPS_MM)*1000
    elif kind == "rotate":
        rotation[k] = (rotation[k] + rng.choice((90, 180, 270))) % 360
    elif kind == "swap":
        j = int(rng.integers(problem.count - 1))
        j += j >= k
        centre[[k, j]] = centre[[j, k]]
        moved.append(j)
    else:
        target = length_target(problem, layout, k)
        centre[k] += (target - centre[k])*rng.choice((.25, .5, 1.0))
    centre[moved] = snap(problem, centre, rotation, grid_um)[moved]
    candidate = Layout(centre, rotation)
    return candidate if is_legal(problem, candidate, gap_um) else None


def length_descent(problem, layout, rng, gap_um, grid_um=1000, patience=400):
    """Greedy exact-length descent with legal moves; no thermal evaluation."""
    best = float(pin_manhattan_um(problem, layout).sum())
    stale = 0
    while stale < patience:
        candidate = mutate(problem, layout, rng, gap_um, grid_um)
        if candidate is not None:
            length = float(pin_manhattan_um(problem, candidate).sum())
            if length < best:
                layout, best, stale = candidate, length, 0
                continue
        stale += 1
    return layout
