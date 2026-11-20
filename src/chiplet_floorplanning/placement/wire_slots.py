"""Joint row and column reassignment on occupied, thermally interchangeable slots."""

from dataclasses import dataclass
from itertools import permutations

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from .geometry import boxes, rotate


@dataclass
class WirePattern:
    """One power map in original-slot order and its cheapest realized netlist."""
    power_w: np.ndarray
    chip_to_slot: np.ndarray
    wire_m: float


def _axis_costs(coordinates, line_id, terminals, delta_um):
    """Index permutations map original line -> destination line on this axis."""
    orders = np.asarray(list(permutations(range(len(coordinates)))), dtype=int)
    left, right = line_id[terminals].T
    terms, counts = np.unique(np.column_stack((left, right, delta_um)),
                              axis=0, return_counts=True)
    wire_um = np.zeros(len(orders))
    for (first, second, offset), multiplicity in zip(terms, counts):
        span = coordinates[orders[:, int(first)]] - coordinates[orders[:, int(second)]]
        wire_um += multiplicity * np.abs(span + offset)
    return orders, wire_um / 1e6


def _power_orders(orders, costs, power_grid, axis, available_m):
    """For identical post-move power grids retain the cheapest projected wiring."""
    kept = {}
    eligible = np.flatnonzero(costs <= available_m)
    for k in eligible:
        order = orders[k]
        grid = np.take(power_grid, np.argsort(order), axis=axis)
        key = grid.tobytes()
        if key not in kept or costs[k] < kept[key][1]:
            kept[key] = (order, costs[k])
    return list(kept.values()), len(eligible)


def line_patterns(problem, start, cap_m, *, wire_tol_m=1e-9):
    """All feasible thermal patterns reachable by permuting whole rows and columns.

    Geometry and material occupancy must stay fixed. Pins remain attached to their
    chiplets with their original orientations. Complexity grows factorially with
    the number of lines per axis. Bounds from this domain apply only within it.
    """
    xy = start.centre_um
    x, col = np.unique(xy[:, 0], return_inverse=True)
    y, row = np.unique(xy[:, 1], return_inverse=True)
    slot = np.full((len(y), len(x)), -1, dtype=int)
    slot[row, col] = np.arange(problem.count)
    rect = boxes(problem, start)
    if (len(x) * len(y) != problem.count or np.any(slot < 0)
            or not np.allclose(rect[:, 2:] - rect[:, :2], rect[0, 2:] - rect[0, :2],
                               rtol=0, atol=1e-8)):
        raise ValueError("row and column reassignment requires a full grid of equal footprints")

    pins = problem.pin_chip
    offsets = rotate(problem.pin_offset_um, start.rotation_deg[pins])
    delta = offsets[:, 0] - offsets[:, 1]
    xo, wx = _axis_costs(x, col, pins, delta[:, 0])
    yo, wy = _axis_costs(y, row, pins, delta[:, 1])
    power_grid = problem.power_w[slot]
    limit = cap_m + wire_tol_m
    x_kept, nx = _power_orders(xo, wx, power_grid, 1, limit - wy.min())
    y_kept, ny = _power_orders(yo, wy, power_grid, 0, limit - wx.min())
    patterns = {}
    # Axis permutations commute, so discarding a more expensive identical
    # intermediate power map cannot remove a better thermal/length pair.
    for cols, x_cost in x_kept:
        for rows, y_cost in y_kept:
            wire = float(x_cost + y_cost)
            if wire > limit:
                continue
            assignment = slot[rows[row], cols[col]]
            powers = np.empty_like(problem.power_w)
            powers[assignment] = problem.power_w
            key = powers.tobytes()
            if key not in patterns or wire < patterns[key].wire_m:
                patterns[key] = WirePattern(powers, assignment, wire)
    sorted_y = np.sort(wy)
    count = sum(int(np.searchsorted(sorted_y, limit - cost, side="right")) for cost in wx)
    return list(patterns.values()), dict(x_orders=len(xo), y_orders=len(yo),
        x_within_budget=nx, y_within_budget=ny, x_power_orders=len(x_kept),
        y_power_orders=len(y_kept), feasible_identity_assignments=count,
        distinct_feasible_power_maps=len(patterns), minimum_wire_m=float(wx.min()+wy.min()))


def forced_edge_components(problem, start, cap_m, *, wire_tol_m=1e-9):
    """A connected graph of forced relative grid displacements certifies rigidity.

    Allow each edge the entire wire slack above the sum of per-edge minima.
    Its allowed lattice displacements then include its displacement in every
    feasible permutation, even on a grid with nonuniform spacing.
    """
    xy = start.centre_um
    left, right = np.where(~np.eye(problem.count, dtype=bool))
    spans = xy[left] - xy[right]
    grid = np.column_stack([np.unique(axis, return_inverse=True)[1] for axis in xy.T])
    steps = grid[left] - grid[right]
    pins = problem.pin_chip
    offsets = rotate(problem.pin_offset_um, start.rotation_deg[pins])
    delta = offsets[:, 0] - offsets[:, 1]
    # An on-die net contributes a fixed length independent of its slot.
    on_die = pins[:, 0] == pins[:, 1]
    minimum = float(np.abs(delta[on_die]).sum())
    lengths = [np.abs(spans + d).sum(axis=1) for d in delta[~on_die]]
    minima = np.array([v.min() for v in lengths])
    minimum += minima.sum()
    slack = (cap_m + wire_tol_m) * 1e6 - minimum
    fixed = []
    for pair, wire, least in zip(pins[~on_die], lengths, minima):
        possible = steps[wire <= least + slack + 1e-6]
        if len(possible) and np.all(possible == possible[0]):
            fixed.append(pair)
    edges = np.asarray(fixed, dtype=int).reshape(-1, 2)
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])),
                       shape=(problem.count, problem.count))
    components = connected_components(graph, directed=False, return_labels=False)
    return dict(sum_edge_minima_m=float(minimum/1e6), forced_edges=len(edges),
                components=int(components), all_relative_positions_fixed=bool(components == 1))
