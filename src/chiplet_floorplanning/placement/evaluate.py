"""Exact layout evaluation, constructive sampling and physical comparison metrics.

Temperature is the declared FV model's power-layer peak (degC); length is the
two-pin source-pin Manhattan lower bound (m). Neither is routed wirelength,
timing or a calibrated junction temperature.
"""
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from .geometry import boxes, is_legal, pin_manhattan_um
from .problem import Layout
from .thermal import solve_peak, thermal_case_data


def thermal_key(problem, layout):
    """Uniform isotropic dies: the thermal problem depends only on occupied boxes."""
    return boxes(problem, layout).round(6).tobytes()


def _peak(args):
    problem, layout, gap_um, resolution = args
    result = solve_peak(thermal_case_data(problem, layout, gap_um, resolution))
    if abs(result["energy_balance_error_w"]) > 1e-6*result["source_power_w"]:
        raise ArithmeticError("FV energy balance failed")
    return result["peak_power_layer_c"]


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
            peaks = list(self.pool.map(_peak, jobs, chunksize=chunk))
        elif self.workers > 1 and len(jobs) > 1:
            with ProcessPoolExecutor(self.workers) as pool:
                peaks = list(pool.map(_peak, jobs, chunksize=chunk))
        else:
            peaks = [_peak(job) for job in jobs]
        self.cache.update(zip(todo, peaks))
        self.solves += len(jobs)
        return np.array([self.cache[key] for key in keys])


def sample_legal(problem, gap_um, rng, grid_um=1000):
    """Place chiplets one at a time, uniformly over remaining legal grid corners.

    Not uniform over the joint legal set; restarts when a chiplet has no room.
    """
    width, height = problem.carrier_um
    while True:
        rotation = rng.choice((0, 90, 180, 270), size=problem.count)
        size = np.where((rotation % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
        centre = np.zeros((problem.count, 2))
        placed = []
        for k in rng.permutation(problem.count):
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
            pick = rng.choice(choices)
            centre[k] = (x0.flat[pick] + size[k, 0]/2, y0.flat[pick] + size[k, 1]/2)
            placed.append(k)
        else:
            layout = Layout(centre, rotation)
            assert is_legal(problem, layout, gap_um)
            return layout


def pareto_front(length_m, peak_c):
    """Indices of the non-dominated (length, peak) points, sorted by length."""
    order = np.lexsort((peak_c, length_m))
    front, best = [], np.inf
    for i in order:
        if peak_c[i] < best:
            front.append(int(i))
            best = peak_c[i]
    return front


def coolest_within(length_m, peak_c, length_cap_m):
    """Main metric: the single layout with the lowest peak among L <= cap (or None)."""
    ok = np.flatnonzero(np.asarray(length_m) <= length_cap_m)
    return None if not ok.size else int(ok[np.argmin(np.asarray(peak_c)[ok])])


def shortest_within(length_m, peak_c, peak_cap_c):
    """Reverse metric: the single layout with the shortest length among T <= cap (or None)."""
    ok = np.flatnonzero(np.asarray(peak_c) <= peak_cap_c)
    return None if not ok.size else int(ok[np.argmin(np.asarray(length_m)[ok])])
