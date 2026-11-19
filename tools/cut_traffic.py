"""Test straight-channel wire cost and cut-limited unicast throughput on moe-server."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from itertools import permutations
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

from case3_phy_geometry import CAP_M, NEIGHBOURS, PAYLOAD_FRACTION, REACH_MM, RING, bank
from chiplet_floorplanning.placement import Layout, Problem, is_legal
from chiplet_floorplanning.placement.geometry import boxes, pin_points_um
from mixed_phy import PROFILES_BY_BIT

EVIDENCE = Path(__file__).resolve().parents[1] / "docs/evidence"
MATCHINGS = (((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2)))
EDGE_GBPS = 1024
TARGET_TB_S = 0.80


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def channels(problem, layout):
    """Yield each nontrivial straight channel once per axis, from rigid die boxes."""
    bounds = boxes(problem, layout)
    for axis in (0, 1):
        order = np.argsort(bounds[:, axis], kind="stable")
        starts = bounds[order, axis]
        ends = np.maximum.accumulate(bounds[order, axis + 2])
        for i in np.flatnonzero(starts[1:] - ends[:-1] >= 1.0):
            right = np.zeros(problem.count, dtype=bool)
            right[order[i + 1 :]] = True
            yield axis, right, float(starts[i + 1] - ends[i])


def geometry_case(job):
    data, prior = job
    name = prior["case"]
    source = data / "physical-calibration/atplace-import-v1" / (name + ".json")
    archive = data / "rs-grb-v4" / name.lower() / "layouts.npz"
    assert digest(source) == prior["case_sha256"]
    assert digest(archive) == prior["layout_archive_sha256"]
    problem = Problem.from_imported(json.loads(source.read_text()))
    assert np.all(
        abs(problem.pin_offset_um) <= problem.size_um[problem.pin_chip] / 2 + 1e-7
    )
    a, b = problem.pin_chip.T
    tested = layouts_with_channels = zero_crossings = 0
    max_net_error_um = max_sum_error_m = 0.0
    widest = None
    with np.load(archive) as z:
        for index, (xy, rot, wire_m) in enumerate(
            zip(z["centre_um"], z["rotation_deg"], z["length_m"])
        ):
            layout = Layout(xy, rot)
            assert is_legal(problem, layout, 0)
            eligible = list(channels(problem, layout))
            if not eligible:
                continue
            layouts_with_channels += 1
            pins = pin_points_um(problem, layout)
            lengths = abs(pins[:, 0] - pins[:, 1]).sum(axis=1)
            assert abs(lengths.sum() / 1e6 - wire_m) < 1e-7
            for axis, right, gap_um in eligible:
                delta_um = min(1000.0, gap_um)
                moved = xy.copy()
                moved[right, axis] -= delta_um
                shifted = pin_points_um(problem, Layout(moved, rot))
                new_lengths = abs(shifted[:, 0] - shifted[:, 1]).sum(axis=1)
                measured = lengths - new_lengths
                cross = right[a] != right[b]
                n = int(cross.sum())
                net_error = float(np.max(abs(measured - cross * delta_um)))
                sum_error = abs(float(measured.sum()) - n * delta_um) / 1e6
                assert net_error < 1e-6 and sum_error < 1e-8
                tested += 1
                zero_crossings += int(n == 0)
                max_net_error_um = max(max_net_error_um, net_error)
                max_sum_error_m = max(max_sum_error_m, sum_error)
                if widest is None or gap_um > widest["gap_um"]:
                    widest = dict(
                        layout_index=index,
                        axis="xy"[axis],
                        gap_um=gap_um,
                        crossing_signals=n,
                        move_um=delta_um,
                        measured_wire_reduction_m=float(measured.sum() / 1e6),
                    )
        layouts = len(z["centre_um"])
    assert layouts == prior["layouts"]
    return dict(
        case=name,
        dies=problem.count,
        layouts=layouts,
        channels_tested=tested,
        layouts_with_channels=layouts_with_channels,
        layouts_without_channels=layouts - layouts_with_channels,
        zero_signal_channels=zero_crossings,
        max_per_pin_error_um=max_net_error_um,
        max_total_error_m=max_sum_error_m,
        widest_channel=widest,
        source_sha256=digest(source),
        archive_sha256=digest(archive),
    )


def witness_channels(data, evidence):
    row = next(
        r for r in evidence["threshold_witnesses"] if r["minimum_fast_from_bound"] == 2
    )
    cfg = row["actual_config"]
    case = data / "physical-calibration/atplace-import-v1/Case3.json"
    p = Problem.from_imported(json.loads(case.read_text()))
    xy = np.array(row["centres_um"])
    lay = Layout(xy, np.array(cfg["rotation_deg"]))
    assert is_legal(p, lay, 0)
    active = list(channels(p, lay))
    ends = boxes(p, lay)
    size_mm = (ends[:, 2:] - ends[:, :2]) / 1000
    memory = (p.pin_chip >= 4).any(axis=1)
    mem_pins = pin_points_um(p, lay)[memory]
    modes = []
    for mask in (0, row["mask"], 15):
        cpus = []
        indices = []
        for e, (a, b) in enumerate(RING):
            profile = PROFILES_BY_BIT[(mask >> e) & 1]
            assert profile.modules * 16 * profile.rate_gt_s == EDGE_GBPS
            pads = []
            for i, j in ((a, b), (b, a)):
                side = cfg["sides"][i][NEIGHBOURS[i].index(j)]
                pads.append(xy[i] + 1000 * bank(tuple(size_mm[i]), side, profile)[0])
            cpus.append(np.stack(pads, axis=1))
            indices.extend([(a, b)] * len(pads[0]))
        pin_chips = np.vstack([p.pin_chip[memory], indices])
        pins = np.concatenate([mem_pins, *cpus], axis=0)
        length = abs(pins[:, 0] - pins[:, 1]).sum(axis=1)
        if mask == row["mask"]:
            assert abs(length.sum() / 1e6 - cfg["wire_m"]) < 1e-8
        rows = []
        for axis, right, gap_um in active:
            cross = right[pin_chips[:, 0]] != right[pin_chips[:, 1]]
            d = min(1000.0, gap_um)
            shifted = pins.copy()
            shifted[:, :, axis] -= right[pin_chips] * d
            saved = length - abs(shifted[:, 0] - shifted[:, 1]).sum(axis=1)
            assert np.max(abs(saved - d * cross)) < 1e-6
            logical_edges = sum(right[a] != right[b] for a, b in RING)
            rows.append(
                dict(
                    axis="xy"[axis],
                    high_side_dies=np.flatnonzero(right).tolist(),
                    gap_mm=gap_um / 1000,
                    cpu_signals=int(cross[len(mem_pins) :].sum()),
                    memory_signals=int(cross[: len(mem_pins)].sum()),
                    cpu_raw_capacity_each_direction_gbps=int(logical_edges) * EDGE_GBPS,
                    move_mm=d / 1000,
                    saved_wire_m=float(saved.sum() / 1e6),
                )
            )
        wire_m = float(length.sum() / 1e6)
        longest_mm = float(length[len(mem_pins) :].max() / 1000)
        modes.append(
            dict(
                mask=mask,
                length_m=wire_m,
                max_cpu_signal_mm=longest_mm,
                wire_budget_met=wire_m <= CAP_M,
                cpu_reach_met=longest_mm <= REACH_MM + 1e-10,
                channels=rows,
            )
        )
    return dict(layout=row["id"], modes=modes)


def network_matrices():
    """Enumerate all simple paths for twelve directed commodities including long detours."""
    arcs = sorted({arc for i, j in RING for arc in ((i, j), (j, i))})
    pairs = list(permutations(range(4), 2))
    paths = []
    for k, (i, j) in enumerate(pairs):
        remaining = sorted(set(range(4)) - {i, j})
        for n in range(len(remaining) + 1):
            for middle in permutations(remaining, n):
                nodes = (i, *middle, j)
                links = list(zip(nodes, nodes[1:]))
                if all(e in arcs for e in links):
                    paths.append((k, links))
    incidence = np.zeros((len(arcs), len(paths) + 1))
    supply = np.zeros((len(pairs), len(paths) + 1))
    short_routes = {}
    for col, (k, links) in enumerate(paths):
        supply[k, col] = 1
        for arc in links:
            incidence[arcs.index(arc), col] = 1
        if len(links) <= 2:
            short_routes.setdefault(k, []).append(col)
    assert all(
        len(v) == (1 if pairs[k] in arcs else 2) for k, v in short_routes.items()
    )
    matching_id = [
        next(m for m, group in enumerate(MATCHINGS) if tuple(sorted(pair)) in group)
        for pair in pairs
    ]
    return incidence, supply, short_routes, matching_id


def traffic_sweep():
    inc, supply, short, matching_id = network_matrices()
    objective = np.zeros(inc.shape[1])
    objective[-1] = -1
    samples = []
    reference = []
    max_lp_error = max_routing_error = 0.0
    crossings = 0
    grids = 40
    for i in range(grids + 1):
        for j in range(grids - i + 1):
            shares = np.array([i, j, grids - i - j]) / grids
            mapped = []
            for diagonal in range(3):
                direct = np.delete(shares, diagonal)
                physical_shares = np.r_[direct, shares[diagonal]]
                demand = physical_shares[matching_id]
                supply[:, -1] = -demand
                result = linprog(
                    objective,
                    A_ub=inc,
                    b_ub=np.ones(8),
                    A_eq=supply,
                    b_eq=np.zeros(len(demand)),
                    bounds=(0, None),
                    method="highs",
                )
                assert result.success, result.message
                lp_scale = float(-result.fun)
                predicted = 1 / (shares[diagonal] + max(direct))
                max_lp_error = max(max_lp_error, abs(lp_scale - predicted) * EDGE_GBPS)
                # A second, explicit route uses one direct path or halves on both two-hop paths.
                witness = np.zeros(len(objective))
                witness[-1] = predicted
                for k, cols in short.items():
                    witness[cols] = predicted * demand[k] / len(cols)
                err = max(
                    float(abs(supply @ witness).max()),
                    float(abs((inc @ witness).max() - 1)),
                )
                max_routing_error = max(max_routing_error, err * EDGE_GBPS)
                assert abs(lp_scale - predicted) < 1e-8 and err < 1e-8
                delivered = lp_scale * EDGE_GBPS * 4 * PAYLOAD_FRACTION / 8000
                mapped.append(delivered)
                if i == 18 and j == 18:
                    reference.append(
                        dict(
                            diagonal_matching=diagonal,
                            diagonal_share=shares[diagonal],
                            per_cpu_raw_gbps=lp_scale * EDGE_GBPS,
                            aggregate_payload_TB_s=delivered,
                            target_met=delivered >= TARGET_TB_S,
                        )
                    )
            assert mapped[int(np.argmin(shares))] >= max(mapped) - 1e-10
            crossings += int(min(mapped) < TARGET_TB_S <= max(mapped))
            samples.append(max(mapped) / min(mapped))
    return dict(
        raw_gbps_per_directed_edge=EDGE_GBPS,
        payload_fraction=PAYLOAD_FRACTION,
        synthetic_target_TB_s=TARGET_TB_S,
        share_step=1 / grids,
        labelled_matrices=len(samples),
        labelled_mapping_trials=3 * len(samples),
        matrices_crossing_target_by_mapping=crossings,
        max_mapping_ratio=max(samples),
        max_lp_formula_error_gbps=max_lp_error,
        max_constructive_flow_error_gbps=max_routing_error,
        reference_shares=[0.45, 0.45, 0.10],
        reference_mappings=reference,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    prior = EVIDENCE / "case3-joint-clearance-v1.json"
    selective = EVIDENCE / "case3-selective-rate-v1.json"
    cases = json.loads(prior.read_text())["source_case_checks"]["cases"]
    with ProcessPoolExecutor(args.workers) as pool:
        geometry = list(pool.map(geometry_case, [(args.data, x) for x in cases]))
    result = dict(
        driver_sha256=digest(Path(__file__)),
        prior_sha256={f.name: digest(f) for f in (prior, selective)},
        geometry=geometry,
        physical_ring=witness_channels(args.data, json.loads(selective.read_text())),
        traffic=traffic_sweep(),
    )
    with args.output.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")


if __name__ == "__main__":
    main()
