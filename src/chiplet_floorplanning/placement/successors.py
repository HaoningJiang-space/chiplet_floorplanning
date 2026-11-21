"""Geometrically certified followers and sparse thermal scoring of their joint endpoints."""
from itertools import product

import numpy as np
from scipy import sparse
from scipy.optimize import linprog

from .geometry import boxes, pin_manhattan_um
from .pin_reach import PinReachCell, required_travel_mm
from .search import layout_key


def follower_landing(cell, start, leader, step, followers, radius):
    """Fix the leader endpoint, lock unlisted dies and minimise the group's L1 travel (mm)."""
    n = cell.problem.count
    xy = start.centre_um.T.ravel() / 1000
    bounds = cell.bounds.copy()
    for j, old in enumerate(xy):
        die, axis = j % n, j // n
        if die == leader:
            low = high = old + step[axis]
        elif die in followers:
            low, high = old - radius, old + radius
        else:
            low = high = old
        lo, hi = cell.bounds[j]
        if max(lo, low) > min(hi, high) + 1e-10:
            return None
        bounds[j] = max(lo, low), max(max(lo, low), min(hi, high))
    ident = sparse.eye(2*n, cell.nvar)
    travel = sparse.eye(2*n)
    mat = sparse.bmat([[cell.A, None], [ident, -travel], [-ident, -travel]], format='csr')
    result = linprog(np.r_[np.zeros(cell.nvar), np.ones(2*n)], A_ub=mat,
                     b_ub=np.r_[cell.b, xy, -xy], bounds=bounds+[(0, None)]*(2*n), method='highs')
    if result.status == 2:
        return None
    if not result.success:
        raise RuntimeError(result.message)
    pose = cell._layout(result.x)
    if pose is not None:
        actual = (pose.centre_um-start.centre_um)/1000
        locked = [i for i in range(n) if i != leader and i not in followers]
        if (np.abs(actual).max() > radius+1e-9 or np.any(np.abs(actual[locked])>1e-9)
                or np.max(np.abs(actual[leader]-step)) > 1e-9):
            return None
        lengths = pin_manhattan_um(cell.problem, pose) / 1000
        if np.all(lengths <= cell.limits_mm+1e-9) and lengths.sum()/1000 <= cell.cap_m+1e-9:
            return pose
    return None


def joint_endpoints(problem, start, reach_mm, cap_m, peaks, gap_um=100, compensate=False):
    """Build all endpoints before observing any candidate temperature."""
    cell = PinReachCell(problem, start, gap_um, reach_mm, cap_m)
    hot = int(np.argmax(peaks))
    xy = start.centre_um / 1000
    dist2 = ((xy - xy[hot])**2).sum(axis=1)
    dist2[hot] = np.inf
    partners = np.arange(problem.count) != hot
    leaders = [hot]
    if partners.any():
        leaders.append(int(np.flatnonzero(partners)[np.argmax((problem.power_w/dist2)[partners])]))
    radius = float(np.median(problem.size_um.min(axis=1))/2000)
    attempts, candidates = [], []
    seen = {layout_key(start)}
    for fraction in (1., .5):
        for dx, dy in product((-1, 0, 1), repeat=2):
            if not (dx or dy):
                continue
            step = radius*fraction*np.array([dx, dy])
            pins, bounds = required_travel_mm(problem, start, reach_mm, np.tile(step,(problem.count,1)), gap_um)
            for leader in leaders:
                follow = np.flatnonzero(bounds[leader] > 1e-8)
                pose = follower_landing(cell, start, leader, step, set(follow), radius)
                opened = compensate and pose is None
                if opened:
                    pose = follower_landing(cell, start, leader, step, set(range(problem.count)), radius)
                record = dict(leader=leader, step_mm=step.tolist(), followers=follow.tolist(),
                              lower_mm=bounds[leader,follow].tolist(), pin_lower_mm=pins[leader,follow].tolist(),
                              opened=opened, candidate=None)
                if pose is not None and layout_key(pose) not in seen:
                    record['candidate'] = len(candidates)
                    candidates.append(pose)
                    seen.add(layout_key(pose))
                attempts.append(record)
    return radius, candidates, attempts


def separations(xy, observers):
    dist = np.linalg.norm(xy[observers, None] - xy[None, :], axis=2)
    dist[np.arange(len(observers)), observers] = np.inf
    return dist


def successor_order(problem, start, peaks, radius_mm, gap_um=100):
    """Rank possible replacement hotspots using an upper bound on this point-source proxy."""
    xy = start.centre_um / 1000
    size = (boxes(problem,start)[:,2:] - boxes(problem,start)[:,:2]) / 1000
    dies = np.arange(problem.count)
    distance = separations(xy, dies)
    min_legal = (size[:,None,:] + size[None,:,:]).min(axis=2)/2 + gap_um/1000
    closest = np.maximum(distance-2*np.sqrt(2)*radius_mm, min_legal)
    heating = (1/closest - 1/distance) @ problem.power_w * (1000/(2*np.pi*400))
    return np.argsort(-(peaks+heating), kind='stable').tolist()


def proxy_peaks(problem, start, candidate, peaks, observers):
    """Starting die peaks plus signed off-die temperature changes at co-moving centres."""
    obs = np.asarray(observers, dtype=int)
    before = separations(start.centre_um/1000, obs)
    after = separations(candidate.centre_um/1000, obs)
    return peaks[obs] + ((1/after - 1/before) @ problem.power_w)*(1000/(2*np.pi*400))
