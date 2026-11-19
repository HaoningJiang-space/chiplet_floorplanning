"""Predict linear capacity cost on arbitrary graphs and check against directed flow LPs."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix, csr_matrix, eye, hstack, kron, vstack
from scipy.sparse.csgraph import shortest_path

from chiplet_floorplanning.placement import Layout, Problem, is_legal, pin_manhattan_um
from cut_traffic import EVIDENCE, digest
from ring_capacity import workloads

MODULE_GBPS = 256
SIGNALS = 44


def shortest_design(edges, price, demand):
    """Route one copy of each symmetric pair on a minimum-price path and mirror its return."""
    nodes = len(demand)
    a, b = edges.T
    graph = csr_matrix((price, (a, b)), shape=(nodes, nodes))
    dist, pred = shortest_path(graph, directed=False, return_predecessors=True)
    index = {tuple(sorted(e)): i for i, e in enumerate(edges)}
    installed = np.zeros(len(edges))
    cost = 0.0
    for src, dst in np.argwhere(np.triu(demand, 1) > 0):
        amount = demand[src, dst]
        assert np.isfinite(dist[src, dst])
        cost += amount * dist[src, dst]
        node = dst
        while node != src:
            parent = pred[src, node]
            installed[index[tuple(sorted((node, parent)))]] += amount
            node = parent
    assert np.isclose(installed @ price, cost, atol=1e-8, rtol=1e-10)
    return float(cost), installed


def flow_design(
    edges, price, demand, cap=None, *, min_hops=False, integer_capacity=False
):
    """Size symmetric ports. Independent directed commodities aggregate by source."""
    n = len(demand)
    m = len(edges)
    assert np.allclose(demand, demand.T) and np.all(np.diag(demand) == 0)
    src = np.flatnonzero(demand.sum(axis=1))
    arcs = np.vstack([edges, edges[:, ::-1]])
    tail, head = arcs.T
    columns = np.arange(2 * m)
    incidence = coo_matrix(
        (
            np.r_[np.ones(2 * m), -np.ones(2 * m)],
            (np.r_[tail, head], np.tile(columns, 2)),
        ),
        shape=(n, 2 * m),
    ).tocsr()
    balance = -demand[src].astype(float)
    balance[np.arange(len(src)), src] += demand[src].sum(axis=1)
    conservation = hstack(
        [kron(eye(len(src)), incidence), csr_matrix((len(src) * n, m))], format="csr"
    )
    combined = kron(np.ones((1, len(src))), eye(2 * m))
    limits = hstack([combined, -vstack([eye(m), eye(m)])], format="csr")
    objective = np.r_[
        np.full(len(src) * 2 * m, float(min_hops)), np.zeros(m) if min_hops else price
    ]
    bounds = [(0, None)] * (len(src) * 2 * m) + [
        (0, c) for c in (cap if cap is not None else [None] * m)
    ]
    result = linprog(
        objective,
        A_eq=conservation,
        b_eq=balance.ravel(),
        A_ub=limits,
        b_ub=np.zeros(2 * m),
        bounds=bounds,
        method="highs",
        integrality=(
            np.r_[np.zeros(len(src) * 2 * m), np.ones(m)] if integer_capacity else None
        ),
        options={"mip_rel_gap": 0.0} if integer_capacity else None,
    )
    assert result.success, result.message
    if integer_capacity:
        assert result.mip_gap <= 1e-8
        assert np.max(abs(result.x[-m:] - np.rint(result.x[-m:]))) < 1e-6
    residual = max(
        np.max(abs(conservation @ result.x - balance.ravel())),
        np.max(limits @ result.x),
    )
    assert residual < 1e-6 and min(result.x) >= -1e-7
    directed = result.x[:-m].reshape(len(src), 2, m).sum(axis=0)
    # Average a route and its reverse. Each ordered pair retains its offered service.
    load = directed.mean(axis=0)
    return float(result.fun), load, float(residual)


def case_check(job):
    data, record, demand_set = job
    name = record["case"]
    source = data / "physical-calibration/atplace-import-v1" / (name + ".json")
    archive = data / "rs-grb-v4" / name.lower() / "layouts.npz"
    assert (
        digest(source) == record["case_sha256"]
        and digest(archive) == record["layout_archive_sha256"]
    )
    p = Problem.from_imported(json.loads(source.read_text()))
    i = record["shortest"]["index"]
    with np.load(archive) as z:
        layout = Layout(z["centre_um"][i], z["rotation_deg"][i])
    assert is_legal(p, layout, 0)
    lengths = pin_manhattan_um(p, layout) / 1e6
    assert abs(lengths.sum() - record["shortest"]["actual_wire_m"]) < 1e-7
    mask = p.pin_chip[:, 0] != p.pin_chip[:, 1]
    edges, inv = np.unique(
        np.sort(p.pin_chip[mask], axis=1), axis=0, return_inverse=True
    )
    price = (
        np.bincount(inv, weights=lengths[mask])
        / np.bincount(inv)
        * SIGNALS
        / MODULE_GBPS
    )
    assert min(price) > 0
    graph = csr_matrix((price, tuple(edges.T)), shape=(p.count, p.count))
    connected = np.isfinite(shortest_path(graph, directed=False))
    results = []
    for workload, d in demand_set.items():
        demand = np.where(connected, d, 0)
        predicted, capacities = shortest_design(edges, price, demand)
        optimal, _, residual = flow_design(edges, price, demand)
        assert abs(predicted - optimal) < 1e-7
        allowance = float(MODULE_GBPS * price[capacities > 0].sum())
        scales = []
        # The odd neighbors distinguish high traffic from divisibility by a 256 Gbit/s module.
        for scale in (1, 16, 127, 128, 129):
            lower = predicted * scale
            rounded = float(
                np.ceil(capacities * scale / MODULE_GBPS) @ price * MODULE_GBPS
            )
            assert lower - 1e-8 <= rounded < lower + allowance
            trial = dict(scale=scale, lower_m=lower, rounded_m=rounded)
            if int(name[4:]) <= 5:
                exact, _, err = flow_design(
                    edges,
                    price * MODULE_GBPS,
                    demand * scale / MODULE_GBPS,
                    integer_capacity=True,
                )
                assert lower - 1e-7 <= exact <= rounded + 1e-7
                trial.update(
                    exact_integer_m=exact, integer_residual_gbps=err * MODULE_GBPS
                )
            scales.append(trial)
        results.append(
            dict(
                workload=workload,
                one_module_per_used_edge_m=allowance,
                scales=scales,
                positive_pairs=int((np.triu(demand) > 0).sum()),
                excluded_pairs=int((np.triu(d - demand) > 0).sum()),
                predicted_m=predicted,
                flow_lp_m=optimal,
                flow_residual_gbps=residual,
                shortest_routed_capacity_gbps=capacities.tolist(),
            )
        )
    return dict(
        case=name,
        layout_index=i,
        nodes=p.count,
        edges=edges.tolist(),
        price_m_per_gbps=price.tolist(),
        workloads=results,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    prior = EVIDENCE / "case3-joint-clearance-v1.json"
    cases = sorted(
        json.loads(prior.read_text())["source_case_checks"]["cases"],
        key=lambda c: int(c["case"][4:]),
    )
    rng = np.random.default_rng(0)
    jobs = [(args.data, c, workloads(c["dies"], rng)) for c in cases]
    with ProcessPoolExecutor(5) as pool:
        rows = list(pool.map(case_check, jobs))
    with args.output.open("x") as f:
        json.dump(
            dict(
                driver_sha256=digest(Path(__file__)),
                prior_sha256=digest(prior),
                cases=rows,
            ),
            f,
            allow_nan=False,
        )


if __name__ == "__main__":
    main()
