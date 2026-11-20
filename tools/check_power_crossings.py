"""Independent pin-by-pin feasibility check for putting a hot die in any cold slot."""

import numpy as np

from chiplet_floorplanning.placement.geometry import pin_points_um


def hot_to_cold(problem, start, longest_mm):
    xy = start.centre_um
    pins = problem.pin_chip
    local_offsets = pin_points_um(problem, start) - xy[pins]
    n = problem.count
    # Construct world coordinates for both pins at every candidate slot.
    allowed = []
    for (i, j), (left, right) in zip(pins, local_offsets):
        a, b = xy + left, xy + right
        distance = np.abs(a[:, None, :] - b[None, :, :]).sum(axis=2)
        pair = distance <= (longest_mm + 1e-9) * 1000
        if i != j:
            np.fill_diagonal(pair, False)
        allowed.append(pair)

    def propagate(domains):
        rounds = 0
        while True:
            rounds += 1
            before = domains.copy()
            for (i, j), pair in zip(pins, allowed):
                if i == j:
                    domains[i] &= pair.diagonal()
                else:
                    domains[i] &= pair[:, domains[j]].any(axis=1)
                    domains[j] &= pair[domains[i], :].any(axis=0)
            sizes = domains.sum(axis=1)
            if (sizes == 0).any() or not domains.any(axis=0).all():
                return False, rounds
            single = sizes == 1
            occupied = domains[single].sum(axis=0)
            if (occupied > 1).any():
                return False, rounds
            domains[np.ix_(~single, occupied == 1)] = False
            if np.array_equal(before, domains):
                return True, rounds

    levels = np.unique(problem.power_w)
    if len(levels) != 2:
        raise ValueError("the crossing diagnostic expects two power classes")
    cold = problem.power_w == levels[0]
    records = []
    for die in np.flatnonzero(~cold):
        domains = np.ones((n, n), bool)
        domains[die] = cold
        survives, rounds = propagate(domains)
        # A simultaneous set of local supports is necessary, not sufficient.
        # Keep the weak test's failures, then split its unresolved disjunction
        # into individual cold destinations. No choices for any other die.
        unresolved = []
        checked = 0
        if survives:
            for slot in np.flatnonzero(cold):
                specific = np.ones((n, n), bool)
                specific[die] = False
                specific[die, slot] = True
                possible, _ = propagate(specific)
                checked += 1
                if possible:
                    unresolved.append(int(slot))
        records.append(dict(die=int(die), contradiction=not survives, rounds=rounds,
                            individual_slots_checked=checked, surviving_slots=unresolved))
    return dict(forced_hot_dies=len(records), contradictions=sum(v['contradiction'] for v in records),
                individual_slots_checked=sum(v['individual_slots_checked'] for v in records),
                unresolved_pairs=sum(len(v['surviving_slots']) for v in records), records=records)
