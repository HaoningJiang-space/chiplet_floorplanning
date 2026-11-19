"""Exact port costs and spatial power for the two equal-bandwidth Case3 link options."""

from functools import lru_cache
from itertools import product

import numpy as np

from case3_phy_geometry import (
    NEIGHBOURS,
    PROFILES,
    REACH_MM,
    RING,
    STATES,
    bank,
    edge_matrices,
    memory_states,
    sizes_mm,
)
from check_interface_cut import MID
from chiplet_floorplanning.placement import (
    Layout,
    is_legal,
    pin_manhattan_um,
    solve,
    thermal_case_data,
)

from chiplet_floorplanning.model import DEFAULT_NODE_LIMIT

PROFILES_BY_BIT = (PROFILES["wide"], MID)
MASKS = np.arange(16)
BITS = (MASKS[:, None] >> np.arange(4)) & 1
FROZEN_EDGES = dict(zip(RING, range(4)))
EDGE_AT = [
    [FROZEN_EDGES[tuple(sorted((i, j)))] for j in NEIGHBOURS[i]] for i in range(4)
]


@lru_cache(maxsize=8192)
def edge_options(a_size, b_size, delta):
    return [
        edge_matrices(a_size, b_size, np.array(delta), profile)
        for profile in PROFILES_BY_BIT
    ]


def configurations(p, row, bundles):
    xy = np.array(row["centres_um"]) / 1000
    size = sizes_mm(p, row["parity"])
    mem, turns = memory_states(xy, row["parity"], bundles)
    costs, lengths = {}, {}
    for e, (a, b) in enumerate(RING):
        opts = edge_options(tuple(size[a]), tuple(size[b]), tuple(xy[b] - xy[a]))
        sums, reach = np.moveaxis(np.array(opts), 1, 0)
        index = np.ix_(
            STATES[:, NEIGHBOURS[a].index(b)], STATES[:, NEIGHBOURS[b].index(a)]
        )
        allowed = np.where(reach <= REACH_MM + 1e-10, sums, np.inf)
        costs[a, b] = allowed[:, index[0], index[1]][BITS[:, e]]
        lengths[a, b] = reach[:, index[0], index[1]]
    # Condition on ports of CPUs 0 and 3. CPU 1 and CPU 2 then minimize independently.
    best = np.broadcast_to(
        mem[0, :, None] + mem[3, None, :], (16, len(STATES), len(STATES))
    ).copy()
    middle = []
    for i in (1, 2):
        path = (
            costs[0, i][:, :, :, None]
            + mem[i, None, None, :, None]
            + costs[i, 3][:, None, :, :]
        )
        middle.append(path.argmin(axis=2))
        best += path.min(axis=2)
    left, right = np.unravel_index(best.reshape(16, -1).argmin(axis=1), best.shape[1:])
    idx = MASKS, left, right
    states = np.array([left, middle[0][idx], middle[1][idx], right]).T
    results = []
    for mask, config in enumerate(states):
        wire = best[mask, left[mask], right[mask]]
        if not np.isfinite(wire):
            results.append(None)
            continue
        states_idx = np.arange(4), config
        longest = max(
            lengths[a, b][BITS[mask, e], config[a], config[b]]
            for e, (a, b) in enumerate(RING)
        )
        results.append(
            dict(
                wire_m=float(wire),
                memory_m=float(mem[states_idx].sum()),
                max_cpu_signal_mm=float(longest),
                latency_ns=4.125 + float(longest) / 150,
                sides=STATES[config].tolist(),
                rotation_deg=(90 * turns[states_idx].T.ravel()).tolist(),
            )
        )
    return results


def pin_check(p, row, mask, cfg):
    xy = np.array(row["centres_um"]) / 1000
    layout = Layout(np.array(row["centres_um"]), np.array(cfg["rotation_deg"]))
    assert is_legal(p, layout, 0)
    memory = pin_manhattan_um(p, layout)[(p.pin_chip >= 4).any(axis=1)].sum() / 1e6
    size = sizes_mm(p, row["parity"])
    bundle = []
    for e, (a, b) in enumerate(RING):
        prof = PROFILES_BY_BIT[BITS[mask, e]]
        pads = []
        for i, j in ((a, b), (b, a)):
            side = cfg["sides"][i][NEIGHBOURS[i].index(j)]
            assert side != layout.rotation_deg[i] // 90
            off, _ = bank(tuple(size[i]), side, prof)
            assert np.all(abs(off) <= size[i] / 2 + 1e-10)
            pads.append(xy[i] + off)
        d = abs(pads[0] - pads[1]).sum(axis=1)
        centroid = float(abs(pads[0].mean(axis=0) - pads[1].mean(axis=0)).sum())
        assert len(d) == 44 * prof.modules and d.mean() + 1e-9 >= centroid
        bundle.append(
            dict(
                n=len(d),
                centroid_mm=centroid,
                wire_m=float(d.sum() / 1000),
                longest_mm=float(d.max()),
            )
        )
    span = float(np.ptp(xy[:4], axis=0).sum())
    assert sum(z["centroid_mm"] for z in bundle) >= 2 * span - 31.2 - 1e-8
    assert abs(memory + sum(z["wire_m"] for z in bundle) - cfg["wire_m"]) < 1e-8
    assert abs(memory - cfg["memory_m"]) < 1e-8
    assert abs(max(z["longest_mm"] for z in bundle) - cfg["max_cpu_signal_mm"]) < 1e-8
    return bundle


def exhaustive_wire(p, row, mask):
    """Independent port-edge enumeration using individual pins and direct Manhattan lengths."""
    from chiplet_floorplanning.placement.geometry import rotate

    xy = np.asarray(row["centres_um"]) / 1000
    sizes = sizes_mm(p, row["parity"])
    states = np.array(list(product(range(12), repeat=4)))
    total = np.zeros(len(states))
    for i in range(4):
        match = (p.pin_chip == i).any(axis=1) & (p.pin_chip == i + 4).any(axis=1)
        off = p.pin_offset_um[match].copy() / 1000
        rev = p.pin_chip[match, 0] != i
        off[rev] = off[rev, ::-1]
        costs = np.full(12, np.inf)
        for t in [row["parity"][i], row["parity"][i] + 2]:
            src = xy[i] + rotate(off[:, 0], 90 * t)
            m = min(
                abs(src - xy[i + 4] - rotate(off[:, 1], 90 * u)).sum() / 1000
                for u in range(4)
            )
            free = (STATES != t).all(axis=1)
            costs[free] = np.minimum(costs[free], m)
        total += costs[states[:, i]]
    for e, (a, b) in enumerate(RING):
        prof = PROFILES_BY_BIT[BITS[mask, e]]
        table = np.full((4, 4), np.inf)
        for sa, sb in product(range(4), repeat=2):
            v = (
                xy[a]
                + bank(tuple(sizes[a]), sa, prof)[0]
                - xy[b]
                - bank(tuple(sizes[b]), sb, prof)[0]
            )
            length = abs(v).sum(axis=1)
            if length.max() <= 25 + 1e-10:
                table[sa, sb] = length.sum() / 1000
        total += table[
            STATES[states[:, a], NEIGHBOURS[a].index(b)],
            STATES[states[:, b], NEIGHBOURS[b].index(a)],
        ]
    return float(total.min())


def temperature(p, row, mask, cfg, grid, *, node_limit=DEFAULT_NODE_LIMIT):
    layout = Layout(np.array(row["centres_um"]), np.array(cfg["rotation_deg"]))
    data = thermal_case_data(p, layout, 0, grid)
    sizes = sizes_mm(p, row["parity"])
    for i, chip in enumerate(data["chiplets"][:4]):
        size = sizes[i]
        profiles = [PROFILES_BY_BIT[BITS[mask, e]] for e in EDGE_AT[i]]
        rects = np.array(
            [
                np.round(bank(tuple(size), side, prof)[1] + np.tile(size / 2, 2), 9)
                for side, prof in zip(cfg["sides"][i], profiles)
            ]
        )
        assert np.all(rects[:, :2] >= -1e-10) and np.all(rects[:, 2:] <= size + 1e-10)
        assert np.any(
            np.minimum(rects[0, 2:], rects[1, 2:])
            <= np.maximum(rects[0, :2], rects[1, :2]) + 1e-10
        )
        xs = np.unique([0, size[0], *rects[:, 0], *rects[:, 2]])
        ys = np.unique([0, size[1], *rects[:, 1], *rects[:, 3]])
        chip["rotation_deg"] = 0
        chip["size_mm"] = dict(width=size[0], height=size[1])
        blocks = []
        for x, x1 in zip(xs, xs[1:]):
            for y, y1 in zip(ys, ys[1:]):
                area = (x1 - x) * (y1 - y)
                power = area * p.power_w[i] / size.prod()
                centre = np.array([(x + x1) / 2, (y + y1) / 2])
                for rect, profile in zip(rects, profiles):
                    if np.all(centre > rect[:2]) and np.all(centre < rect[2:]):
                        power += (
                            area
                            * profile.full_phy_w
                            / (8 * np.prod(rect[2:] - rect[:2]))
                        )
                blocks.append(
                    dict(
                        id="cell" + str(len(blocks)),
                        rect_mm=dict(x=x, y=y, width=x1 - x, height=y1 - y),
                        power_w=float(power),
                        provenance="Uniform core and localized equal-throughput PHY banks",
                    )
                )
        assert abs(sum(x["power_w"] for x in blocks) - p.power_w[i] - 2.048) < 1e-8
        chip["blocks"] = blocks
    obs, _, _ = solve(data, node_limit=node_limit)
    assert (
        abs(obs["source_power_w"] - 688.192) < 1e-7
        and abs(obs["energy_balance_error_w"]) < 1e-7
    )
    return dict(
        peak_c=obs["peak_power_layer_c"],
        balance_error_w=abs(obs["energy_balance_error_w"]),
    )
