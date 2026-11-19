"""Size shared full-duplex capacity for measured, directed NAS payload matrices."""

import argparse
from hashlib import sha256
from concurrent.futures import ProcessPoolExecutor
from itertools import permutations
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import block_diag, coo_matrix, csr_matrix, eye, hstack, kron, vstack
from scipy.sparse.csgraph import connected_components, dijkstra

from case3_phy_geometry import CAP_M, LIMIT_C, PAYLOAD_FRACTION, REACH_MM, RING
from chiplet_floorplanning.placement import Problem
from cut_traffic import EVIDENCE, digest, network_matrices
from mixed_phy import bank_temperature
from module_capacity import CAPACITY, GRIDS, MODULES, UNIFORM, bank_table, profile

NAMES = ("IS", "BH", "WH", "SH")
TARGET = 0.20


def payload_digest(payload):
    """Identify the logical benchmark input independently of wall times in benchmark logs."""
    inputs = [
        payload["source_sha256"],
        payload["benchmark_class"],
        payload["ranks"],
        [
            (
                k,
                payload["workloads"][k]["verification"],
                payload["workloads"][k]["payload_bytes"],
            )
            for k in NAMES
        ],
    ]
    return sha256(json.dumps(inputs, separators=(",", ":")).encode()).hexdigest()


def read_shared(path, evidence):
    run = json.loads(path.read_text())
    if "logical_payload_sha256" in run:
        assert run["logical_payload_sha256"] == evidence["logical_payload_sha256"]
        assert run["price_data_sha256"] == evidence["graph_prices_sha256"]
    else:
        assert digest(path) == evidence["raw_sha256"]["shared.json"]
    return run


def mapped_traffic(payload, mapping, n):
    result = []
    kept = []
    for name in NAMES:
        sent = np.asarray(payload["workloads"][name]["payload_bytes"])
        aggregate = np.zeros((n, n), dtype=np.int64)
        np.add.at(aggregate, (mapping[:, None], mapping[None, :]), sent)
        np.fill_diagonal(aggregate, 0)
        kept.append(int(aggregate.sum()))
        assert kept[-1] > 0
        result.append(aggregate * (TARGET * 8000 / (PAYLOAD_FRACTION * kept[-1])))
    return np.array(result), kept


def continuous_design(edges, prices, demands):
    """Directed primal with one installed capacity shared by every scenario and direction."""
    n = len(demands[0])
    m = len(edges)
    tail, head = np.vstack([edges, edges[:, ::-1]]).T
    columns = np.arange(2 * m)
    incidence = coo_matrix(
        (
            np.r_[np.ones(2 * m), -np.ones(2 * m)],
            (np.r_[tail, head], np.tile(columns, 2)),
        ),
        shape=(n, 2 * m),
    ).tocsr()
    balances = []
    eq = []
    usage = []
    for demand in demands:
        src = np.flatnonzero(demand.sum(axis=1) > 0)
        b = -demand[src].copy()
        b[np.arange(len(src)), src] += demand[src].sum(axis=1)
        balances.append(b.ravel())
        eq.append(kron(eye(len(src)), incidence))
        usage.append(kron(np.ones((1, len(src))), eye(2 * m)))
    b = np.concatenate(balances)
    eq = hstack([block_diag(eq), csr_matrix((len(b), m))], format="csr")
    usage = block_diag(usage, format="csr")
    ub = hstack([usage, -vstack([eye(m)] * (2 * len(demands)))], format="csr")
    objective = np.r_[np.zeros(usage.shape[1]), prices]
    opt = linprog(
        objective,
        A_ub=ub,
        b_ub=np.zeros(ub.shape[0]),
        A_eq=eq,
        b_eq=b,
        bounds=(0, None),
        method="highs",
    )
    assert opt.success, opt.message
    loads = (usage @ opt.x[:-m]).reshape(len(demands), 2, m)
    installed = opt.x[-m:]
    assert np.max(abs(eq @ opt.x - b)) < 1e-6
    assert np.max(abs(installed - loads.max(axis=(0, 1)))) < 1e-6
    # A valid lower bound can be checked without access to flows or node LP potentials.
    tolls = np.maximum(0, -opt.ineqlin.marginals.reshape(len(demands), 2, m))
    tolls *= prices / np.maximum(prices, tolls.sum(axis=(0, 1)))
    lower = 0.0
    for toll, d in zip(tolls, demands):
        graph = csr_matrix((toll.ravel(), (tail, head)), shape=(n, n))
        dist = dijkstra(graph, directed=True)
        used = d > 0
        lower += float(dist[used] @ d[used])
    gap = float(opt.fun - lower)
    assert abs(gap) < 1e-7 * max(1, opt.fun)
    return dict(
        cost_m=float(opt.fun),
        lower_certificate_m=lower,
        capacity_gbps=installed.tolist(),
        toll_m_per_gbps=tolls.tolist(),
        max_conservation_residual_gbps=float(abs(eq @ opt.x - b).max()),
    )


def graph_trial(job):
    case, payload = job
    n = case["nodes"]
    edges = np.array(case["edges"])
    prices = np.array(case["price_m_per_gbps"])
    graph = csr_matrix((np.ones(len(edges)), tuple(edges.T)), shape=(n, n))
    _, labels = connected_components(graph, directed=False)
    nodes = np.flatnonzero(labels == np.argmax(np.bincount(labels)))
    group = edges[labels[edges[:, 0]] == labels[nodes[0]]]
    index = (
        np.arange(16) * len(nodes) // 16
        if len(nodes) >= 16
        else np.arange(16) % len(nodes)
    )
    mapping = nodes[index]
    demand, kept = mapped_traffic(payload, mapping, n)
    solo = [continuous_design(edges, prices, [d]) for d in demand]
    shared = continuous_design(edges, prices, demand)
    most = int(np.argmax([z["cost_m"] for z in solo]))
    reverse = continuous_design(edges, prices, [demand[most], demand[most].T])
    assert abs(solo[most]["cost_m"] - reverse["cost_m"]) < 1e-7
    overlay = float(np.max([r["capacity_gbps"] for r in solo], axis=0) @ prices)
    assert (
        solo[most]["cost_m"] <= shared["cost_m"] + 1e-7
        and shared["cost_m"] <= overlay + 1e-7
    )
    tree_cost = None
    if len(group) == len(nodes) - 1:
        capacities = np.zeros(len(edges))
        for i, (a, b) in enumerate(edges):
            if labels[a] != labels[nodes[0]]:
                continue
            rest = np.delete(edges, i, axis=0)
            _, parts = connected_components(
                csr_matrix((np.ones(len(rest)), tuple(rest.T)), shape=(n, n)),
                directed=False,
            )
            side = parts == parts[a]
            assert not side[b]
            capacities[i] = max(
                max(d[np.ix_(side, ~side)].sum(), d[np.ix_(~side, side)].sum())
                for d in demand
            )
        tree_cost = float(capacities @ prices)
        assert abs(tree_cost - shared["cost_m"]) < 1e-7
    return dict(
        case=case["case"],
        nodes=n,
        links=len(edges),
        mapped_component_nodes=len(nodes),
        rank_map=mapping.tolist(),
        off_die_bytes=dict(zip(NAMES, kept)),
        solo=dict(zip(NAMES, solo)),
        shared=shared,
        independently_sized_overlay_m=overlay,
        reverse_test=NAMES[most],
        with_reverse=reverse,
        tree_cut_m=tree_cost,
    )


def physical_capacity(args):
    index, D = args
    inc, balance, _, _ = network_matrices()
    pairs = list(permutations(range(4), 2))
    arcs = sorted([*RING, *[(b, a) for a, b in RING]])
    ids = [RING.index(tuple(sorted(arc))) for arc in arcs]
    cap = CAPACITY[index][ids]
    rates = []
    for d in D:
        balance[:, -1] = -np.array([d[a, b] for a, b in pairs])
        objective = np.zeros(inc.shape[1])
        objective[-1] = -1
        opt = linprog(
            objective,
            A_eq=balance,
            b_eq=np.zeros(len(pairs)),
            A_ub=inc,
            b_ub=cap,
            bounds=(0, None),
            method="highs",
        )
        assert opt.success, opt.message
        rates.append(TARGET * opt.x[-1])
    return rates


def routed_load(d, cap):
    inc, supply, _, _ = network_matrices()
    inc = inc[:, :-1]
    supply = supply[:, :-1]
    arcs = sorted([*RING, *[(b, a) for a, b in RING]])
    ids = [RING.index(tuple(sorted(e))) for e in arcs]
    need = np.array([d[a, b] for a, b in permutations(range(4), 2)])
    opt = linprog(
        inc.sum(axis=0),
        A_eq=supply,
        b_eq=need,
        A_ub=inc,
        b_ub=cap[ids],
        bounds=(0, None),
        method="highs",
    )
    assert opt.success, opt.message
    loads = inc @ opt.x
    assert np.max(loads - cap[ids]) < 1e-7 and max(abs(supply @ opt.x - need)) < 1e-7
    return np.array(
        [[loads[arcs.index((a, b))], loads[arcs.index((b, a))]] for a, b in RING]
    )


def thermal_job(job):
    p, row, mods, power, g = job
    obs = bank_temperature(
        p,
        row,
        row["actual_config"],
        g,
        [profile(m) for m in mods],
        power,
        node_limit=450000,
    )
    return (row["id"], mods, power), g, obs


def physical(p, rows, payload, pool):
    demand, kept = mapped_traffic(payload, np.arange(16) % 4, 4)
    rates = np.array(
        list(
            pool.map(
                physical_capacity,
                [(i, demand) for i in range(len(MODULES))],
                chunksize=16,
            )
        )
    )
    records = []
    thermal = {}
    for row in rows:
        memory, cost, reach = bank_table(p, row)
        wire = memory + cost[np.arange(4), MODULES].sum(axis=1)
        longest = reach[np.arange(4), MODULES].max(axis=1)
        legal = longest <= REACH_MM + 1e-9
        cases = []
        for target in (TARGET, 0.24):
            supported = legal[:, None] & (rates >= target - 1e-9)
            common = supported.all(axis=1)
            report = dict(
                target_TB_s=target,
                feasible_portfolios=int(common.sum()),
                feasible_by_phase=dict(zip(NAMES, supported.sum(axis=0).tolist())),
                within_wire_cap=int((common & (wire <= CAP_M + 1e-10)).sum()),
            )
            for method, allowed in (("sized", common), ("uniform", common & UNIFORM)):
                if not allowed.any():
                    report[method] = None
                    continue
                best = int(np.argmin(np.where(allowed, wire, np.inf)))
                mods = tuple(MODULES[best].tolist())
                cap = CAPACITY[best]
                modes = {}
                for name, d, rate in zip(NAMES, demand, rates[best]):
                    flow = routed_load(d * (target / TARGET), cap)
                    watts = tuple(
                        ((0.25 * cap + 0.75 * flow.mean(axis=1)) / 1000).tolist()
                    )
                    rec = dict(
                        achievable_payload_TB_s=float(rate),
                        directed_raw_gbps=flow.tolist(),
                        endpoint_w=watts,
                        phy_w=2 * sum(watts),
                    )
                    thermal.setdefault((row["id"], mods, watts), []).append(rec)
                    modes[name] = rec
                report[method] = dict(
                    modules=mods,
                    total_wire_m=float(wire[best]),
                    max_cpu_signal_mm=float(longest[best]),
                    modes=modes,
                )
            cases.append(report)
        records.append(dict(layout=row["id"], cases=cases))
    jobs = [
        (p, row, mods, watts, g)
        for row in rows
        for rid, mods, watts in thermal
        if rid == row["id"]
        for g in GRIDS
    ]
    for key, g, obs in pool.map(thermal_job, jobs):
        for rec in thermal[key]:
            rec.setdefault("grids", {})[g] = obs
    for layout in records:
        for case in layout["cases"]:
            for method in ("sized", "uniform"):
                rec = case[method]
                if rec:
                    rec["max_peak_c"] = max(
                        v["peak_c"]
                        for mode in rec["modes"].values()
                        for v in mode["grids"].values()
                    )
                    rec["joint_target_met"] = bool(
                        rec["max_peak_c"] <= LIMIT_C
                        and rec["total_wire_m"] <= CAP_M + 1e-10
                    )
    return dict(
        off_die_bytes=dict(zip(NAMES, kept)),
        layout_trials=records,
        thermal_solves=len(jobs),
        directed_path_lp_count=rates.size,
        full_port_max_common_TB_s=float(rates[-1].min()),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for k in ("data", "payload", "output"):
        ap.add_argument("--" + k, required=True, type=Path)
    ap.add_argument("--workers", type=int, default=7)
    args = ap.parse_args()
    evidence = json.loads((EVIDENCE / "capacity-cost-v1.json").read_text())
    data = args.data / "capacity-cost-2fd0b43/scale-final.json"
    assert digest(data) == evidence["raw_sha256"]["scale-final.json"]
    src = args.data / "physical-calibration/atplace-import-v1/Case3.json"
    assert digest(src) == evidence["physical_model"]["raw_source_sha256"]
    payload = json.loads(args.payload.read_text())
    assert all(payload["workloads"][k]["verification"] == "SUCCESSFUL" for k in NAMES)
    cases = json.loads(data.read_text())["cases"]
    rows = json.loads((EVIDENCE / "case3-selective-rate-v1.json").read_text())[
        "threshold_witnesses"
    ]
    problem = Problem.from_imported(json.loads(src.read_text()))
    with ProcessPoolExecutor(args.workers) as pool:
        records = list(pool.map(graph_trial, [(c, payload) for c in cases]))
        result = physical(problem, rows, payload, pool)
    with args.output.open("x") as f:
        json.dump(
            dict(
                driver_sha256=digest(Path(__file__)),
                payload_sha256=digest(args.payload),
                logical_payload_sha256=payload_digest(payload),
                price_data_sha256=digest(data),
                graphs=records,
                physical=result,
            ),
            f,
            allow_nan=False,
        )


if __name__ == "__main__":
    main()
