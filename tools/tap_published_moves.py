"""TAP-derived coordinate proposals, isolated from the frozen online pilot.

This is an adapter component, not a complete published-method reproduction.
Every attempted geometry goes through the common evaluator and proposal cap.
"""
import copy


class NeighbourhoodExhausted(Exception):
    """No legal one-step neighbour; says nothing about global feasibility."""


def close_move(evaluator, placement, rng):
    order = list(range(len(placement)))
    rng.shuffle(order)
    grid = evaluator.domain['centre_grid_um']
    for index in order:
        directions = [(0, -grid), (0, grid), (-grid, 0), (grid, 0)]
        rng.shuffle(directions)
        for dx, dy in directions:
            candidate = copy.deepcopy(placement)
            candidate[index]['centre_x_um'] += dx
            candidate[index]['centre_y_um'] += dy
            row = evaluator.evaluate(candidate, 'tap_close')
            if row is not None:
                return row
    raise NeighbourhoodExhausted('all one-grid-step moves rejected; global feasibility unknown')


def propose(evaluator, placement, rng, mode=None, jump_attempts=10001):
    """First legal close/jump candidate, with all rejected attempts charged.

    Uses one injected Python RNG instead of upstream's mixed NumPy/Python RNGs.
    A jump optionally rotates the *current* orientation by 90 degrees. Exhausted
    jumps fall back to close moves with the same row return type. Budget and
    numerical failures propagate unchanged, never masquerading as no neighbour.
    """
    if mode not in (None, 'close', 'jump'):
        raise ValueError('unknown move mode')
    if type(jump_attempts) is not int or jump_attempts < 1:
        raise ValueError('positive integer retry limit required')
    domain = evaluator.domain
    grid, side = domain['centre_grid_um'], domain['interposer_side_um']
    if side % grid or side // grid < 2 or set(domain['rotations_deg']) != {0, 90, 180, 270}:
        raise ValueError('adapter requires divisible centre grid and four rotations')
    mode = mode or ('jump' if rng.random() < 0.1 else 'close')
    if mode == 'jump':
        for _ in range(jump_attempts):
            candidate = copy.deepcopy(placement)
            index = rng.randrange(len(candidate))
            candidate[index]['centre_x_um'] = rng.randrange(1, side // grid) * grid
            candidate[index]['centre_y_um'] = rng.randrange(1, side // grid) * grid
            candidate[index]['rotation_deg'] = (candidate[index]['rotation_deg'] + 90*rng.randrange(2)) % 360
            row = evaluator.evaluate(candidate, 'tap_jump')
            if row is not None:
                return row
    return close_move(evaluator, placement, rng)
