"""Exact layout evaluation, constructive sampling and physical comparison metrics.

Temperature is the declared FV model's power-layer peak (degC), with each die's
own peak kept alongside so local degradation stays visible; length is the
two-pin source-pin Manhattan lower bound (m), also available per net. None of
these is routed wirelength, timing or a calibrated junction temperature.
"""
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from .geometry import boxes, is_legal, pin_manhattan_um
from .problem import Layout
from .thermal import die_peaks_c, solve, thermal_case_data


def thermal_key(problem, layout):
    """Uniform isotropic dies: the thermal problem depends only on occupied boxes."""
    return boxes(problem, layout).round(6).tobytes()


def _peaks(args):
    """[global power-layer peak, peak of each die], degC.

    solve() already rejects non-finite, inaccurate or non-conserving solutions.
    """
    problem, layout, gap_um, resolution = args
    summary, rise, edges = solve(thermal_case_data(problem, layout, gap_um, resolution))
    return np.r_[summary["peak_power_layer_c"], die_peaks_c(problem, layout, rise, edges)]


class Evaluator:
    """Use as a context manager to keep one process pool across many batches."""
    def __init__(self, problem, gap_um, resolution=64, workers=1):
        self.problem, self.gap_um, self.resolution, self.workers = problem, gap_um, resolution, workers
        self.cache = {}
        self.solves = 0
        self.pool = None

    def __enter__(self):
        if self.workers > 1:
            self.pool = ProcessPoolExecutor(self.workers)
        return self

    def __exit__(self, *exc):
        if self.pool:
            self.pool.shutdown()
            self.pool = None

    def length_m(self, layout):
        return float(pin_manhattan_um(self.problem, layout).sum()/1e6)

    def max_net_mm(self, layout):
        return float(pin_manhattan_um(self.problem, layout).max()/1000) if len(self.problem.pin_chip) else 0.0

    def die_peaks_c(self, layouts):
        """(n_layouts, n_dies) per-die FV peaks; uses the same cache as peaks_c."""
        self.peaks_c(layouts)
        return np.array([self.cache[thermal_key(self.problem, layout)][1:] for layout in layouts])

    def peaks_c(self, layouts):
        """FV peaks for legal layouts; solves each distinct thermal problem once."""
        keys = [thermal_key(self.problem, layout) for layout in layouts]
        todo = {}
        for key, layout in zip(keys, layouts):
            if key not in self.cache and key not in todo:
                todo[key] = layout
        jobs = [(self.problem, layout, self.gap_um, self.resolution) for layout in todo.values()]
        chunk = max(1, len(jobs)//(4*self.workers))
        if self.pool and len(jobs) > 1:
            peaks = list(self.pool.map(_peaks, jobs, chunksize=chunk))
        elif self.workers > 1 and len(jobs) > 1:
            with ProcessPoolExecutor(self.workers) as pool:
                peaks = list(pool.map(_peaks, jobs, chunksize=chunk))
        else:
            peaks = [_peaks(job) for job in jobs]
        self.cache.update(zip(todo, peaks))
        self.solves += len(jobs)
        return np.array([self.cache[key][0] for key in keys])


def sample_legal(problem, gap_um, rng, grid_um=1000, uniform_tries=20, packed_tries=200):
    """Place chiplets one at a time on legal grid corners; not uniform over the joint legal set.

    First try uniform choices among remaining legal corners. Dense cases dead-end,
    so then pack largest-first toward a random carrier corner, choosing among the
    most compact 5% of legal corners.
    """
    width, height = problem.carrier_um
    area = problem.size_um.prod(axis=1)
    for attempt in range(uniform_tries + packed_tries):
        packed = attempt >= uniform_tries
        rotation = rng.choice((0, 90, 180, 270), size=problem.count)
        size = np.where((rotation % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
        order = np.lexsort((rng.random(problem.count), -area)) if packed else rng.permutation(problem.count)
        flip = rng.integers(2, size=2)
        centre = np.zeros((problem.count, 2))
        placed = []
        for k in order:
            x0, y0 = np.meshgrid(np.arange(0, width - size[k, 0] + 1, grid_um),
                                 np.arange(0, height - size[k, 1] + 1, grid_um), indexing="ij")
            ok = np.ones(x0.shape, bool)
            for j in placed:
                lo, hi = centre[j] - size[j]/2, centre[j] + size[j]/2
                ok &= ((x0 + size[k, 0] + gap_um <= lo[0]) | (hi[0] + gap_um <= x0)
                       | (y0 + size[k, 1] + gap_um <= lo[1]) | (hi[1] + gap_um <= y0))
            choices = np.flatnonzero(ok)
            if not choices.size:
                break
            if packed:
                # Distance from the chosen corner; keep the most compact few percent.
                dx = np.where(flip[0], width - size[k, 0] - x0.flat[choices], x0.flat[choices])
                dy = np.where(flip[1], height - size[k, 1] - y0.flat[choices], y0.flat[choices])
                choices = choices[np.argsort(dx + dy, kind="stable")[:max(1, choices.size//20)]]
            pick = rng.choice(choices)
            centre[k] = (x0.flat[pick] + size[k, 0]/2, y0.flat[pick] + size[k, 1]/2)
            placed.append(k)
        else:
            layout = Layout(centre, rotation)
            assert is_legal(problem, layout, gap_um)
            return layout
    layout = shelf_pack(problem, gap_um, rng, grid_um)
    if layout is None:
        raise RuntimeError("no legal layout found by sampling or shelf packing")
    return layout


def shelf_pack(problem, gap_um, rng, grid_um=1000, shuffles=50):
    """Rows of chiplets sorted by height, left to right; legal fallback start.

    Every lower-left corner is rounded up to the search grid, so search moves
    stay on the same lattice. Tries short-side-up, long-side-up and source
    orientations, shuffling chiplets of equal height. Returns None if no tried
    arrangement fits the carrier.
    """
    up = lambda v: np.ceil(v/grid_um - 1e-9)*grid_um
    width, height = problem.carrier_um
    w, h = problem.size_um[:, 0], problem.size_um[:, 1]
    policies = (np.where(w >= h, 0, 90), np.where(w >= h, 90, 0), np.zeros(problem.count, int))
    for policy in policies:
        for _ in range(shuffles):
            rotation = (policy + 180*rng.integers(2, size=problem.count)) % 360
            size = np.where((rotation % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
            order = np.lexsort((rng.random(problem.count), -size[:, 1]))
            centre = np.zeros((problem.count, 2))
            x = y = row = 0.0
            for k in order:
                if x and x + size[k, 0] > width:
                    x, y, row = 0.0, up(y + row + gap_um), 0.0
                centre[k] = (x + size[k, 0]/2, y + size[k, 1]/2)
                x = up(x + size[k, 0] + gap_um)
                row = max(row, size[k, 1])
            layout = Layout(centre, rotation)
            if is_legal(problem, layout, gap_um):
                return layout
    return None


def _finite(*arrays):
    arrays = [np.asarray(a, dtype=float) for a in arrays]
    if not all(np.isfinite(a).all() for a in arrays):
        raise ValueError("non-finite length or peak reached a metric")
    return arrays


def pareto_front(length_m, peak_c):
    """Indices of the non-dominated (length, peak) points, sorted by length."""
    length_m, peak_c = _finite(length_m, peak_c)
    order = np.lexsort((peak_c, length_m))
    front, best = [], np.inf
    for i in order:
        if peak_c[i] < best:
            front.append(int(i))
            best = peak_c[i]
    return front


def coolest_within(length_m, peak_c, length_cap_m):
    """Main metric: the single layout with the lowest peak among L <= cap (or None)."""
    length_m, peak_c = _finite(length_m, peak_c)
    ok = np.flatnonzero(length_m <= length_cap_m)
    return None if not ok.size else int(ok[np.argmin(peak_c[ok])])


def shortest_within(length_m, peak_c, peak_cap_c):
    """Reverse metric: the single layout with the shortest length among T <= cap (or None)."""
    length_m, peak_c = _finite(length_m, peak_c)
    ok = np.flatnonzero(peak_c <= peak_cap_c)
    return None if not ok.size else int(ok[np.argmin(length_m[ok])])
