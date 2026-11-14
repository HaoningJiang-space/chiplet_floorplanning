"""Legal-move neighbourhoods, exact length descent and batched Pareto local search.

Lower-left corners stay on the grid (default 1 mm). Every proposal is checked
for legality before evaluation; temperatures are exact FV peaks from Evaluator.
"""
import numpy as np

from .evaluate import pareto_front, thermal_key
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
    """One random legal move, or None if the drawn move is illegal."""
    centre, rotation = layout.centre_um.copy(), layout.rotation_deg.copy()
    k = int(rng.integers(problem.count))
    kind = rng.choice(("shift", "rotate", "swap", "pull"), p=(.45, .15, .15, .25))
    if kind == "shift":
        centre[k, rng.integers(2)] += rng.choice((-1, 1))*rng.choice(STEPS_MM)*1000
    elif kind == "rotate":
        rotation[k] = (rotation[k] + rng.choice((90, 180, 270))) % 360
    elif kind == "swap":
        j = int(rng.integers(problem.count - 1))
        j += j >= k
        centre[[k, j]] = centre[[j, k]]
    else:
        target = length_target(problem, layout, k)
        centre[k] += (target - centre[k])*rng.choice((.25, .5, 1.0))
    candidate = Layout(snap(problem, centre, rotation, grid_um), rotation)
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


class _Budget:
    """Admit distinct layouts while their new thermal problems fit the FV-solve budget."""
    def __init__(self, evaluator, fv_solves):
        self.evaluator, self.limit = evaluator, fv_solves
        self.seen, self.pending = set(), set()

    def admit(self, layout):
        key = layout_key(layout)
        if key in self.seen:
            return False
        thermal = thermal_key(self.evaluator.problem, layout)
        new = thermal not in self.evaluator.cache and thermal not in self.pending
        if new and self.evaluator.solves + len(self.pending) >= self.limit:
            return False
        self.seen.add(key)
        if new:
            self.pending.add(thermal)
        return True

    def exhausted(self):
        return self.evaluator.solves + len(self.pending) >= self.limit


def pareto_search(evaluator, initial, rng, fv_solves, batch=96, max_moves=3, grid_um=1000, log=None):
    """Batched Pareto local search on (length, exact FV peak).

    Budget unit: distinct FV solves, including the initial set. Duplicate layouts
    are dropped; a layout whose thermal problem is already solved costs no solve.
    Each generation mutates random archive members with 1..max_moves legal moves
    and evaluates the admitted batch in parallel.
    """
    problem, gap_um = evaluator.problem, evaluator.gap_um
    budget = _Budget(evaluator, fv_solves)
    layouts = [layout for layout in initial if budget.admit(layout)]
    peaks = list(evaluator.peaks_c(layouts))
    budget.pending.clear()
    lengths = [evaluator.length_m(layout) for layout in layouts]
    while layouts and not budget.exhausted():
        archive = pareto_front(np.array(lengths), np.array(peaks))
        children = []
        for _ in range(50*batch):
            if len(children) >= batch or budget.exhausted():
                break
            child = layouts[archive[rng.integers(len(archive))]]
            for _ in range(int(rng.integers(1, max_moves + 1))):
                moved = mutate(problem, child, rng, gap_um, grid_um)
                child = moved if moved is not None else child
            if budget.admit(child):
                children.append(child)
        if not children:
            break
        peaks += list(evaluator.peaks_c(children))
        budget.pending.clear()
        lengths += [evaluator.length_m(child) for child in children]
        layouts += children
        if log:
            front = pareto_front(np.array(lengths), np.array(peaks))
            log(dict(layouts=len(layouts), fv_solves=evaluator.solves, front_size=len(front),
                     min_peak_c=float(min(peaks)), min_length_m=float(min(lengths))))
    return layouts, np.array(lengths), np.array(peaks)
