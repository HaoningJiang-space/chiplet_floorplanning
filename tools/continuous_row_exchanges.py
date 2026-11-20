"""Exact continuous y feasibility for swaps of two adjacent row strips (fixed x)."""

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csr_matrix, vstack

from chiplet_floorplanning.placement.geometry import boxes, is_legal, pin_manhattan_um, pin_points_um
from chiplet_floorplanning.placement.problem import Layout


def row_exchanges(p, start, caps, gap_um=100):
    xy = start.centre_um / 1000
    n = p.count
    xs, col = np.unique(xy[:, 0], return_inverse=True)
    ys, row = np.unique(xy[:, 1], return_inverse=True)
    grid = np.full((len(ys), len(xs)), -1, int)
    grid[row, col] = np.arange(n)
    if np.any(grid < 0) or grid.size != n:
        raise ValueError('expected one die per row-column intersection')
    rect = boxes(p, start)/1000
    # With x fixed, the same-column order fully describes collision avoidance.
    for j in range(1, len(xs)):
        if rect[col == j, 0].min() - rect[col == j-1, 2].max() < gap_um/1000:
            raise ValueError('neighboring columns lack horizontal clearance')
    half_h = (rect[:, 3] - rect[:, 1])/2
    a, b = p.pin_chip.T
    m = len(a)
    pins = pin_points_um(p, start)/1000
    dx = np.abs(pins[:, 0, 0] - pins[:, 1, 0])
    off = pins[:, 0, 1] - xy[a, 1] - pins[:, 1, 1] + xy[b, 1]
    # y_i, full length of each net in mm, maximum length in mm.
    size = n + m + 1
    differences = np.eye(n)[a] - np.eye(n)[b]
    links = np.zeros((3*m, size))
    links[:m, :n] = differences
    links[m:2*m, :n] = -differences
    links[:m, n:n+m] = links[m:2*m, n:n+m] = -np.eye(m)
    links[2*m:, n:n+m] = np.eye(m)
    links[2*m:, -1] = -1
    rhs = np.r_[-dx-off, -dx+off, np.zeros(m)]
    min_total = np.r_[np.zeros(n), np.ones(m), 0.]
    min_longest = np.r_[np.zeros(n+m), 1.]
    records, candidates = [], []
    for r in range(len(ys)-1):
        mid = (ys[r]+ys[r+1])/2
        for width in range(1, min(3, len(xs))+1):
            for c in range(len(xs)-width+1):
                order = grid.copy()
                section = slice(c, c+width)
                order[[r, r+1], section] = order[[r+1, r], section]
                lower, upper = order[:-1, section].ravel(), order[1:, section].ravel()
                spacing = np.zeros((len(lower), size))
                spacing[:, :n] = np.eye(n)[lower] - np.eye(n)[upper]
                mat = csr_matrix(np.vstack((links, spacing)))
                bound = np.r_[rhs, -gap_um/1000 - half_h[lower] - half_h[upper]]
                limits = [(y, y) for y in xy[:, 1]]
                for die in order[r, section]:
                    limits[die] = (half_h[die], mid)
                for die in order[r+1, section]:
                    limits[die] = (mid, p.carrier_um[1]/1000 - half_h[die])
                limits += [(0, None)]*m
                def optimize(cost, z_cap=None, wire_cap=None):
                    matrix, bounds = mat, bound
                    if wire_cap is not None:
                        matrix = vstack((mat, csr_matrix(min_total[None, :])), format='csr')
                        bounds = np.r_[bound, wire_cap]
                    sol = linprog(cost, A_ub=matrix, b_ub=bounds, bounds=limits+[(0, z_cap)], method='highs',
                                  options={'primal_feasibility_tolerance': 1e-9,
                                           'dual_feasibility_tolerance': 1e-9})
                    if sol.status not in (0, 2):
                        raise RuntimeError(sol.message)
                    return sol
                record = dict(lower_row=r, first_col=c, moved=2*width,
                              crosses_power_classes=bool(np.any(p.power_w[order[r, section]] !=
                                                                p.power_w[order[r+1, section]])))
                result = optimize(min_total, z_cap=caps[1]+1e-9)
                record['min_total_m_at_longest'] = float(result.fun/1000) if result.success else None
                if not result.success or result.fun/1000 > caps[0]+1e-9:
                    nearest = optimize(min_longest, wire_cap=(caps[0]+1e-9)*1000)
                    record['min_longest_mm_at_total'] = float(nearest.fun) if nearest.success else None
                    if not nearest.success:
                        loose = optimize(min_total)
                        record['min_total_m_without_link_cap'] = float(loose.fun/1000) if loose.success else None
                        shortest_link = optimize(min_longest)
                        record['min_longest_mm_without_total_cap'] = float(shortest_link.fun) if shortest_link.success else None
                    record['eligible'] = False
                else:
                    coords = start.centre_um.copy()
                    moved = order[r:r+2, section].ravel()
                    coords[moved, 1] = result.x[moved] * 1000
                    layout = Layout(coords, start.rotation_deg)
                    wire = pin_manhattan_um(p, layout)
                    if not is_legal(p, layout, gap_um):
                        raise ValueError('continuous representative requires exact geometry verification')
                    assert wire.sum()/1e6 <= caps[0]+1e-9 and wire.max()/1000 <= caps[1]+1.1e-9
                    i, j = np.triu_indices(n, 1)
                    distance_mm = np.linalg.norm((coords[i]-coords[j])/1000, axis=1)
                    score = float(np.sum(p.power_w[i]*p.power_w[j]/distance_mm))
                    record.update(eligible=True, interaction_w2_per_mm=score)
                    candidates.append((score, layout))
                records.append(record)
    return sorted(candidates, key=lambda item: item[0]), records
