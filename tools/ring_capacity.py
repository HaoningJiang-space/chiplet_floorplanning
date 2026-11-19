"""Compare ring interval bounds against independent, directional splittable-flow LPs."""

import argparse
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix


def interval_limit(capacity, demand):
    """Edge i joins node i to (i+1) mod n. Keep one side of each two-edge cut."""
    n = len(capacity)
    prefix = np.pad(demand, ((1, 0), (1, 0))).cumsum(axis=0).cumsum(axis=1)
    best = float("inf")
    bottleneck = None
    for i, j in combinations(range(n), 2):
        lo, hi = i + 1, j + 1
        internal = prefix[hi, hi] - prefix[lo, hi] - prefix[hi, lo] + prefix[lo, lo]
        outgoing = prefix[hi, n] - prefix[lo, n] - internal
        if outgoing > 0:
            ratio = (capacity[i] + capacity[j]) / outgoing
            if ratio < best:
                best = float(ratio)
                bottleneck = dict(
                    edges=[i, j],
                    one_way_crossing_demand_gbps=int(outgoing),
                    one_way_capacity_gbps=int(capacity[i] + capacity[j]),
                )
    return best, bottleneck


def path_limit(capacity, demand):
    """One flow per simple directed path. Demand equalities share one load multiplier."""
    n = len(capacity)
    pairs = np.argwhere(demand > 0)
    columns = 2 * len(pairs) + 1
    arcs, path_ids = [], []
    for k, (a, b) in enumerate(pairs):
        for direction in (0, 1):
            node = a
            while node != b:
                if direction == 0:
                    arc = node
                    node = (node + 1) % n
                else:
                    node = (node - 1) % n
                    arc = n + node
                arcs.append(arc)
                path_ids.append(2 * k + direction)
    usage = coo_matrix(
        (np.ones(len(arcs)), (arcs, path_ids)), shape=(2 * n, columns)
    ).tocsr()
    k = np.arange(len(pairs))
    demand_rows = np.r_[k, k, k]
    demand_cols = np.r_[2 * k, 2 * k + 1, np.full(len(k), columns - 1)]
    amounts = np.r_[np.ones(2 * len(k)), -demand[tuple(pairs.T)]]
    delivery = coo_matrix(
        (amounts, (demand_rows, demand_cols)), shape=(len(k), columns)
    ).tocsr()
    objective = np.zeros(columns)
    objective[-1] = -1
    cap = np.tile(capacity, 2)
    result = linprog(
        objective,
        A_ub=usage,
        b_ub=cap,
        A_eq=delivery,
        b_eq=np.zeros(len(k)),
        bounds=(0, None),
        method="highs",
    )
    assert result.success, result.message
    error = max(
        float(np.max(usage @ result.x - cap)), float(np.max(abs(delivery @ result.x)))
    )
    assert error < 1e-6 and min(result.x) >= -1e-7
    return float(result.x[-1]), error


def workloads(n, rng):
    local, hubs, spread = (np.zeros((n, n), dtype=int) for _ in range(3))
    for i, j in combinations(range(n), 2):
        if min(j - i, n + i - j) <= 2:
            local[i, j] = rng.integers(2, 17)
        if i == 0 or i == n // 2 or j == n // 2:
            hubs[i, j] = rng.integers(1, 32)
    indices = np.triu_indices(n, k=1)
    keep = rng.choice(len(indices[0]), min(3 * n, len(indices[0])), replace=False)
    spread[indices[0][keep], indices[1][keep]] = rng.integers(1, 30, size=len(keep))
    return {
        key: values + values.T
        for key, values in (("local", local), ("hubs", hubs), ("spread", spread))
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    rng = np.random.default_rng(0)
    rows = []
    for n in (4, 6, 8, 11, 12, 20, 28, 36, 44, 61):
        traffic = workloads(n, rng)
        perm = rng.permutation(n)
        capacities = {
            "uniform": np.full(n, 1024),
            "heterogeneous": rng.choice([256, 512, 768, 1024], size=n),
        }
        for cap_name, cap in capacities.items():
            for name, base_demand in traffic.items():
                for mapping, order in (("identity", np.arange(n)), ("permuted", perm)):
                    demand = base_demand[np.ix_(order, order)]
                    bound, cut = interval_limit(cap, demand)
                    optimal, error = path_limit(cap, demand)
                    assert abs(optimal - bound) <= 1e-8 * max(1, bound)
                    rows.append(
                        dict(
                            nodes=n,
                            capacity_profile=cap_name,
                            workload=name,
                            mapping=mapping,
                            positive_directed_pairs=int((demand > 0).sum()),
                            interval_count=n * (n - 1) // 2,
                            cut_bound=bound,
                            path_lp=optimal,
                            path_primal_error_gbps=error,
                            bottleneck=cut,
                        )
                    )
    output = dict(
        driver_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        rng_seed=0,
        scope="Synthetic bidirectional rings, pairwise symmetric steady unicast, ideal fractional forwarding.",
        trials=rows,
    )
    with args.output.open("x") as f:
        json.dump(output, f, indent=2, allow_nan=False)
        f.write("\n")


if __name__ == "__main__":
    main()
