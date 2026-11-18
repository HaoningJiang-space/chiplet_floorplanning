"""Physical signal banks and deterministic geometry search for the Case3 PHY experiment."""

from dataclasses import dataclass
from functools import lru_cache
from itertools import permutations, product

import numpy as np
from scipy.special import k0

from case3_wire_witness import BundleLengths
from chiplet_floorplanning.placement import Layout, is_legal, pin_manhattan_um

RING = ((0, 1), (0, 2), (1, 3), (2, 3))
# E, N, W, S. The original DRAM pads occupy the local east side of every CPU.
NORMAL = np.array(((1, 0), (0, 1), (-1, 0), (0, -1)))
STATES = np.array(list(permutations(range(4), 2)))
NEIGHBOURS = [[b if a == i else a for a, b in RING if i in (a, b)] for i in range(4)]
CAP_M = 38.95376444850001
LIMIT_C = 109.0
REACH_MM = 25.0
PAYLOAD_FRACTION = 256 / 272


@dataclass(frozen=True)
class Interface:
    modules: int
    rate_gt_s: int
    energy_pj_bit: float
    depth_mm: float

    @property
    def raw_gbps(self):
        return self.modules * 16 * self.rate_gt_s * 2 * len(RING)

    @property
    def full_phy_w(self):
        return self.raw_gbps * self.energy_pj_bit / 1000


PROFILES = {"wide": Interface(8, 8, 1.0, 1.32), "narrow": Interface(2, 32, 1.25, 1.54)}


def sizes_mm(problem, parity):
    size = problem.size_um.copy() / 1000
    for i, odd in enumerate(parity):
        if odd:
            size[i] = size[i, ::-1]
    return size


@lru_cache(maxsize=256)
def bank(size, side, profile):
    """44 matched end-to-end signal positions per module plus the local heat rectangle."""
    normal = NORMAL[side]
    tangent = abs(normal[::-1])
    edge = normal * np.array(size) / 2
    # Receiver-side role assignment is complementary at matching indices.
    # Four signal columns by eleven rows fit within a nominal six-column envelope.
    t = np.arange(profile.modules)[:, None, None] * 0.6 - (profile.modules - 1) * 0.3
    t = t + (np.arange(4)[None, :, None] - 1.5) * 0.1
    z = (np.arange(11)[None, None, :] + 1) * 0.1
    pads = (edge + t[..., None] * tangent - z[..., None] * normal).reshape(-1, 2)
    mid = edge - normal * profile.depth_mm / 2
    half = (tangent * profile.modules * 0.6 + abs(normal) * profile.depth_mm) / 2
    return pads, np.r_[mid - half, mid + half]


@lru_cache(maxsize=1024)
def offset_table(size_a, size_b, side_a, side_b, profile):
    offsets = bank(size_a, side_a, profile)[0] - bank(size_b, side_b, profile)[0]
    ordered = np.sort(offsets, axis=0).T.copy()
    signs = np.array(((1, 1), (1, -1), (-1, 1), (-1, -1)))
    support = (offsets @ signs.T).max(axis=0)
    return ordered, np.pad(np.cumsum(ordered, axis=1), ((0, 0), (1, 0))), support


def edge_matrices(a_size, b_size, delta, profile):
    sums = np.empty((4, 4))
    longest = np.empty_like(sums)
    dx, dy = delta
    signs = np.array([dx + dy, dx - dy, -dx + dy, -dx - dy])
    for a, b in product(range(4), repeat=2):
        ordered, prefix, support = offset_table(a_size, b_size, a, b, profile)
        cost = 0.0
        for h, d in enumerate(delta):
            k = ordered[h].searchsorted(d)
            cost += (2 * k - ordered.shape[1]) * d + prefix[h, -1] - 2 * prefix[h, k]
        sums[a, b] = cost / 1000
        longest[a, b] = (support - signs).max()
    return sums, longest


def memory_states(centres, parity, costs):
    """Minimize unchanged DRAM wire over equivalent rotations for each pair of CPU sides."""
    states_cost = np.full((4, len(STATES)), np.inf)
    turns = np.zeros((4, len(STATES), 2), int)
    for i in range(4):
        dx, dy = (centres[i + 4] - centres[i]) * 1000
        for cpu in (parity[i], parity[i] + 2):
            values = [
                costs.length(i, i + 4, int(cpu), ram, dx, dy) / 1e6 for ram in range(4)
            ]
            ram = int(np.argmin(values))
            change = (STATES != cpu).all(axis=1) & (values[ram] < states_cost[i])
            states_cost[i, change] = values[ram]
            turns[i, change] = [cpu, ram]
    return states_cost, turns


def select_ports(centres, size, mem, turns, profile):
    """Exact minimum wire over the declared candidate side/rotation choices at fixed centres."""
    pair_cost, worst = {}, {}
    for a, b in RING:
        costs, lengths = edge_matrices(
            tuple(size[a]), tuple(size[b]), centres[b] - centres[a], profile
        )
        ai = STATES[:, NEIGHBOURS[a].index(b)]
        bi = STATES[:, NEIGHBOURS[b].index(a)]
        pair_cost[a, b] = np.where(lengths <= REACH_MM + 1e-10, costs, np.inf)[
            np.ix_(ai, bi)
        ]
        worst[a, b] = lengths[np.ix_(ai, bi)]
    # Fix opposite nodes 0 and 3; then nodes 1 and 2 are conditionally independent.
    best = mem[0, :, None] + mem[3, None, :]
    middle = []
    for i in (1, 2):
        three = (
            pair_cost[0, i][:, :, None]
            + mem[i, None, :, None]
            + pair_cost[i, 3][None, :, :]
        )
        best = best + three.min(axis=1)
        middle.append(three.argmin(axis=1))
    end = np.unravel_index(np.argmin(best), best.shape)
    if not np.isfinite(best[end]):
        return None
    states = [end[0], middle[0][end], middle[1][end], end[1]]
    index = np.arange(4), states
    cpu_ram_turns = turns[index]
    max_mm = max(worst[a, b][states[a], states[b]] for a, b in RING)
    return dict(
        wire_m=float(best[end]),
        memory_m=float(mem[index].sum()),
        sides=STATES[states].tolist(),
        rotation_deg=(90 * cpu_ram_turns.T.ravel()).tolist(),
        max_cpu_signal_mm=float(max_mm),
        latency_ns=float(2 + 272 * 8 / (profile.raw_gbps / 8) + max_mm / 150),
    )


def direct_check(p, centres_um, choice, profile):
    centres = centres_um / 1000
    layout = Layout(centres_um, np.array(choice["rotation_deg"]))
    assert is_legal(p, layout, 0)
    size = sizes_mm(p, layout.rotation_deg[:4] // 90 % 2)
    mem = pin_manhattan_um(p, layout)[(p.pin_chip >= 4).any(axis=1)].sum() / 1e6
    lengths = []
    for a, b in RING:
        pads = []
        for i, j in ((a, b), (b, a)):
            side = choice["sides"][i][NEIGHBOURS[i].index(j)]
            assert side != layout.rotation_deg[i] // 90
            offsets, rect = bank(tuple(size[i]), side, profile)
            assert np.all(abs(offsets) <= size[i] / 2 + 1e-12)
            pads.append(centres[i] + offsets)
        lengths.extend(abs(pads[1] - pads[0]).sum(axis=1))
    assert len(lengths) == 4 * 44 * profile.modules
    assert (
        abs(choice["wire_m"] - mem - sum(lengths) / 1000) < 1e-8
        and abs(mem - choice["memory_m"]) < 1e-8
    )
    assert abs(max(lengths) - choice["max_cpu_signal_mm"]) < 1e-8


def candidate_geometries(p, archive, witness):
    choices = {}

    def add(centres, rotation, name, peak=None):
        parity = tuple(int(z) for z in np.asarray(rotation)[:4] // 90 % 2)
        xy = np.asarray(centres)
        key = (tuple(xy.ravel()), parity)
        if key not in choices:
            choices[key] = dict(
                centres_um=xy.tolist(), parity=parity, id=name, base_c=peak
            )
        if name == "reference":
            choices[key].update(id=name, base_c=peak)

    for i, (xy, r, t) in enumerate(
        zip(archive["centre_um"], archive["rotation_deg"], archive["peak_c"])
    ):
        add(xy, r, "archive-" + str(i), float(t))
    for i, pt in enumerate(witness["points"]):
        name = "reference" if i == witness["prior_id"] else "prior-" + str(i)
        add(pt["centre_um"], pt["rotation_deg"], name, pt["checks"]["64"]["peak_c"])
    signs = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]])
    for parity in ((0, 0, 0, 0), (1, 1, 1, 1), (0, 1, 1, 0), (1, 0, 0, 1)):
        size = sizes_mm(p, parity)
        for inset in product((0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0), repeat=2):
            cpus = 19.5 + signs * (19.5 - size[:4] / 2 - inset)
            for axes in product(range(2), repeat=4):
                for extra in (0.0, 2.0):
                    ram = cpus.copy()
                    for i, h in enumerate(axes):
                        ram[i, h] -= signs[i, h] * ((size[i, h] + 9) / 2 + extra)
                    xy = np.vstack([cpus, np.clip(ram, 4.5, 34.5)]) * 1000
                    r = np.array([*parity, 0, 0, 0, 0]) * 90
                    if is_legal(p, Layout(xy, r), 0):
                        add(xy, r, "corner-" + str(len(choices)))
    return list(choices.values())


def heat_score(centres, size, power, radii, weights, self_k):
    var = (size**2).sum(axis=1) / 12
    dist = np.sqrt(
        ((centres[:, None] - centres[None, :]) ** 2).sum(axis=2)
        + var[:, None]
        + var[None, :]
    )
    mutual = k0(dist[:, :, None] / radii) @ weights
    np.fill_diagonal(mutual, 0.0)
    return float(max(self_k + mutual @ power))
