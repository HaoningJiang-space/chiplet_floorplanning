"""Price and certify service for any directed unicast matrix of bounded total rate."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations, permutations
import json
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, maximum_flow

from case3_phy_geometry import CAP_M, LIMIT_C, PAYLOAD_FRACTION, REACH_MM
from chiplet_floorplanning.placement import Problem
from cut_traffic import EVIDENCE, digest
from module_capacity import CAPACITY, EDGES, GRIDS, MODULES, bank_table
from shared_capacity import read_shared, routed_load, thermal_job


def adjacency(n, edges, capacity):
    a, b = edges.T
    graph = csr_matrix(
        (np.tile(capacity, 2), (np.r_[a, b], np.r_[b, a])), shape=(n, n), dtype=np.int64
    )
    graph.eliminate_zeros()
    return graph


def global_cut(graph):
    """Undirected Stoer-Wagner contraction, retaining the actual minimizing partition."""
    weights = graph.toarray()
    n = len(weights)
    groups = [[i] for i in range(n)]
    active = np.ones(n, bool)
    best = np.inf
    side = []
    while active.sum() > 1:
        remaining = active.copy()
        score = np.zeros(n, np.int64)
        prev = None
        while remaining.any():
            candidates = np.flatnonzero(remaining)
            v = candidates[np.argmax(score[candidates])]
            remaining[v] = False
            if not remaining.any():
                if score[v] < best:
                    best = int(score[v])
                    side = groups[v].copy()
                weights[prev, :] += weights[v, :]
                weights[:, prev] = weights[prev, :]
                groups[prev].extend(groups[v])
                active[v] = False
            else:
                score += weights[v]
                prev = v
    other = np.ones(n, bool)
    other[side] = False
    assert int(graph[side][:, other].sum()) == best
    return int(best), side


def all_pairs(graph):
    pairs = list(permutations(range(graph.shape[0]), 2))
    return [int(maximum_flow(graph, a, b).flow_value) for a, b in pairs]


def graph_check(case):
    n = case["nodes"]
    original = np.array(case["edges"])
    _, labels = connected_components(
        adjacency(n, original, np.ones(len(original), dtype=int)), directed=False
    )
    active = labels == np.argmax(np.bincount(labels))
    vertices = np.flatnonzero(active)
    links = active[original[:, 0]]
    edges = np.searchsorted(vertices, original[links])
    rows = []
    for label, modules in (
        ("uniform", np.ones(len(original), dtype=int)),
        ("heterogeneous", 1 + np.arange(len(original)) % 4),
    ):
        g = adjacency(len(vertices), edges, 256 * modules[links])
        cut, side = global_cut(g)
        flows = all_pairs(g)
        assert cut == min(flows)
        rows.append(
            dict(
                profile=label,
                ordered_pairs=len(flows),
                cut_vertices=vertices[side].tolist(),
                cut_raw_gbps=cut,
                minimum_maxflow_raw_gbps=min(flows),
                guaranteed_payload_TB_s=cut * PAYLOAD_FRACTION / 8000,
            )
        )
    return dict(case=case["case"], component_nodes=len(vertices), checks=rows)


def ring_check(cap):
    flows = all_pairs(adjacency(4, EDGES, cap))
    predicted = int(sum(sorted(cap)[:2]))
    assert min(flows) == predicted
    return predicted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for k in ("data", "shared", "output"):
        parser.add_argument("--" + k, type=Path, required=True)
    args = parser.parse_args()
    evidence = json.loads((EVIDENCE / "capacity-cost-v1.json").read_text())
    prices = args.data / "capacity-cost-2fd0b43/scale-final.json"
    src = args.data / "physical-calibration/atplace-import-v1/Case3.json"
    assert (
        digest(prices) == evidence["raw_sha256"]["scale-final.json"]
        and digest(src) == evidence["physical_model"]["raw_source_sha256"]
    )
    prior = json.loads((EVIDENCE / "shared-capacity-v1.json").read_text())
    measured = read_shared(args.shared, prior)["physical"]["layout_trials"]
    p = Problem.from_imported(json.loads(src.read_text()))
    layouts = json.loads((EVIDENCE / "case3-selective-rate-v1.json").read_text())[
        "threshold_witnesses"
    ]
    results = []
    jobs = {}
    with ProcessPoolExecutor(7) as pool:
        graphs = list(pool.map(graph_check, json.loads(prices.read_text())["cases"]))
        guarantee = (
            np.array(list(pool.map(ring_check, CAPACITY, chunksize=16)))
            * PAYLOAD_FRACTION
            / 8000
        )
        for r, observed in zip(layouts, measured):
            assert r["id"] == observed["layout"]
            mem, wire, reach = bank_table(p, r)
            total = mem + wire[np.arange(4), MODULES].sum(axis=1)
            longest = reach[np.arange(4), MODULES].max(axis=1)
            for c in observed["cases"]:
                target = c["target_TB_s"]
                allowed = (guarantee >= target - 1e-10) & (longest <= REACH_MM + 1e-9)
                assert allowed.any()
                i = int(np.argmin(np.where(allowed, total, np.inf)))
                modules = tuple(MODULES[i].tolist())
                expected_min = 15 if target == 0.2 else 16
                assert MODULES[allowed].sum(axis=1).min() == expected_min
                modes = {}
                for a, b in combinations(range(4), 2):
                    demand = np.zeros((4, 4))
                    demand[a, b] = target * 8000 / PAYLOAD_FRACTION
                    load = routed_load(demand, CAPACITY[i])
                    watts = tuple(
                        (
                            (0.25 * CAPACITY[i] + 0.75 * load.mean(axis=1)) / 1000
                        ).tolist()
                    )
                    obs = dict(
                        directed_load_gbps=load.tolist(),
                        endpoint_w=watts,
                        phy_w=2 * sum(watts),
                    )
                    modes[f"{a}-{b}"] = obs
                    jobs.setdefault((r["id"], modules, watts), []).append(obs)
                measured_idx = int(
                    np.ravel_multi_index(c["sized"]["modules"], (5,) * 4)
                )
                results.append(
                    dict(
                        layout=r["id"],
                        target_payload_TB_s=target,
                        minimum_modules=int(expected_min),
                        feasible_portfolios=int(allowed.sum()),
                        modules=modules,
                        total_wire_m=float(total[i]),
                        max_cpu_signal_mm=float(longest[i]),
                        guaranteed_payload_TB_s=float(guarantee[i]),
                        specific_application_wire_m=c["sized"]["total_wire_m"],
                        specific_design_guarantee_TB_s=float(guarantee[measured_idx]),
                        specific_design_modules=c["sized"]["modules"],
                        uniform_wire_m=c["uniform"]["total_wire_m"],
                        terminal_modes=modes,
                    )
                )
        todo = [
            (p, r, mods, w, g)
            for r in layouts
            for rid, mods, w in jobs
            if rid == r["id"]
            for g in GRIDS
        ]
        for key, g, t in pool.map(thermal_job, todo):
            for z in jobs[key]:
                z.setdefault("grids", {})[g] = t
    for r in results:
        r["worst_steady_peak_c"] = max(
            v["peak_c"]
            for z in r["terminal_modes"].values()
            for v in z["grids"].values()
        )
        r["joint_target_met"] = bool(
            r["total_wire_m"] <= CAP_M + 1e-10 and r["worst_steady_peak_c"] <= LIMIT_C
        )
    with args.output.open("x") as f:
        json.dump(
            dict(
                driver_sha256=digest(Path(__file__)),
                shared_sha256=digest(args.shared),
                graphs=graphs,
                ring_portfolios=len(CAPACITY),
                maxflow_per_portfolio=12,
                targets=results,
                unique_thermal_solves=len(todo),
            ),
            f,
            allow_nan=False,
        )


if __name__ == "__main__":
    main()
