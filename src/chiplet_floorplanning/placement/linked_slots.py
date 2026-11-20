"""Enumerate simultaneous fixed-orientation slot moves under pin-length limits."""

from collections import Counter
from functools import lru_cache

import numpy as np

from .geometry import boxes, rotate
from .wire_slots import WirePattern


def _bits(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


def _supported_by(rows):
    """Union of compatible opposite slots for a domain, shared across equal PHY pairs."""
    @lru_cache(maxsize=8192)
    def union(domain):
        result = 0
        for slot in _bits(domain):
            result |= rows[slot]
        return result
    return union


def linked_patterns(problem, start, total_m, longest_mm, *, max_moved=None, node_limit=None,
                    on_feasible=None):
    """All certified leaves up to the node limit. A complete traversal exhausts its domain.

    Slots must be thermally interchangeable and occupied by equal physical footprints.
    Move counts compare each identity's final slot with its own starting slot.
    """
    n = problem.count
    rect = boxes(problem, start)
    if not np.allclose(rect[:, 2:] - rect[:, :2], rect[0, 2:] - rect[0, :2], rtol=0, atol=1e-8):
        raise ValueError("fixed occupied slots require interchangeable footprints")
    same = [1 << i for i in range(n)]
    full = (1 << n) - 1
    budget = n if max_moved is None else max_moved
    xy = start.centre_um
    spans = xy[:, None, :] - xy[None, :, :]
    pins = problem.pin_chip
    offset = rotate(problem.pin_offset_um, start.rotation_deg[pins])
    delta = offset[:, 0] - offset[:, 1]
    lengths, offset_id = np.unique(delta, axis=0, return_inverse=True)
    wire_tables = np.abs(spans[None, :, :, :] + lengths[:, None, None, :]).sum(axis=-1)
    admissible = wire_tables <= (longest_mm + 1e-9) * 1000
    supports = {}
    arcs = []
    for pair, kind in zip(pins, offset_id):
        i, j = map(int, pair)
        if i == j:
            continue  # on-die lengths are fixed; tested when scoring each leaf
        for a, b, allowed in ((i, j, admissible[kind]), (j, i, admissible[kind].T)):
            key = allowed.tobytes()
            if key not in supports:
                rows = tuple(sum(same[k] for k in np.flatnonzero(row)) for row in allowed)
                supports[key] = _supported_by(rows)
            arcs.append((a, b, supports[key]))

    def propagate(domains):
        while True:
            before = domains.copy()
            forced_moves = sum(not d & identity for d, identity in zip(domains, same))
            if forced_moves > budget or 0 in domains:
                return False
            if forced_moves == budget:
                for i, mask in enumerate(domains):
                    if mask & same[i]:
                        domains[i] = same[i]
            fixed = 0
            for mask in domains:
                if mask.bit_count() == 1:
                    if fixed & mask:
                        return False
                    fixed |= mask
            only_once = seen = 0
            for i, mask in enumerate(domains):
                if mask.bit_count() > 1:
                    mask &= ~fixed
                    domains[i] = mask
                only_once = (only_once & ~mask) | (mask & ~seen)
                seen |= mask
            if seen != full or 0 in domains:
                return False
            for i, mask in enumerate(domains):
                unique = mask & only_once
                if unique:
                    if unique.bit_count() > 1:
                        return False
                    domains[i] = unique
            for a, b, support in arcs:
                domains[b] &= support(domains[a])
                if not domains[b]:
                    return False
            if domains == before:
                return True

    counts = Counter()
    by_moved = Counter()
    patterns = {}
    interrupted = False

    def visit(domains):
        nonlocal interrupted
        if node_limit is not None and counts["nodes"] >= node_limit:
            interrupted = True
            return
        counts["nodes"] += 1
        if not propagate(domains):
            return
        open_dies = [i for i, mask in enumerate(domains) if mask.bit_count() > 1]
        if open_dies:
            i = min(open_dies, key=lambda j: (domains[j].bit_count(), bool(domains[j] & same[j]), j))
            # Visit the incumbent side first so a bounded traversal can retain it.
            slots = domains[i]
            choices = ([i] if slots & same[i] else []) + list(_bits(slots & ~same[i]))
            for k in choices:
                child = domains.copy()
                child[i] = same[k]
                visit(child)
                if interrupted:
                    break
            return
        assignment = np.array([mask.bit_length() - 1 for mask in domains])
        wires = wire_tables[offset_id, assignment[pins[:, 0]], assignment[pins[:, 1]]]
        if wires.max(initial=0) > (longest_mm + 1e-9) * 1000:
            return
        counts["within_longest"] += 1
        wire = float(wires.sum()/1e6)
        if wire > total_m + 1e-9:
            return
        by_moved[int(np.count_nonzero(assignment != np.arange(n)))] += 1
        if on_feasible is not None:
            on_feasible(assignment)
        power = np.empty_like(problem.power_w)
        power[assignment] = problem.power_w
        key = power.tobytes()
        if key not in patterns or wire < patterns[key].wire_m:
            patterns[key] = WirePattern(power, assignment, wire)

    visit([full] * n)
    return list(patterns.values()), dict(complete=not interrupted, nodes=counts["nodes"],
        within_longest=counts["within_longest"], feasible_assignments=sum(by_moved.values()),
        by_moved=dict(sorted(by_moved.items())), power_maps=len(patterns))
