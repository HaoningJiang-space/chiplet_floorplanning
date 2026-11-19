"""Predict shared-floorplan feasibility from DC fields, then challenge frozen predictions with AC loads."""

import argparse
from dataclasses import replace
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

import numpy as np
from scipy.sparse import diags
from scipy.sparse.linalg import splu
from scipy.integrate import solve_ivp

from chiplet_floorplanning.package import checked_solution
from chiplet_floorplanning.placement import Layout, Problem, is_legal
from chiplet_floorplanning.placement.decision import guaranteed_amplitude, worst_regret_bounds
from chiplet_floorplanning.placement.geometry import pin_manhattan_um
from chiplet_floorplanning.placement.lp import legalize_relations
from chiplet_floorplanning.placement.thermal import thermal_case_data
from cut_traffic import EVIDENCE, digest
from periodic_layout_choice import package_model


EPS_K = 0.1
FRACTIONS = (0.25, 1.0)
PERIODS = (0.017, 0.137)
GAP_UM = 100
GRID = 32
PROTOCOL = "420946cdf3defaab20c9a5fe39f259bf4cfac116"


def text_digest(path):
    """Hash versioned evidence identically in LF and CRLF checkouts."""
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def cases(sources):
    bank = EVIDENCE / "layout-dominance-v1.json"
    for entry in json.loads(bank.read_bytes())["cases"]:
        name = entry["case"]
        source = sources / (name + ".json")
        assert digest(source) == entry["input_sha256"]
        p = Problem.from_imported(json.loads(source.read_bytes()))
        cap = entry["length_cap_m"]
        designs = []
        for row in entry["layouts"]:
            if row["length_m"] > cap:
                continue
            layout = Layout(np.array(row["centre_um"], float), np.array(row["rotation_deg"], int))
            if not is_legal(p, layout, GAP_UM):
                layout = legalize_relations(p, layout, GAP_UM)
            if layout is not None:
                cost = float(pin_manhattan_um(p, layout).sum() / 1e6)
                if cost <= cap:
                    designs.append((row["layout"], layout, cost))
        yield p, designs, dict(family="ATPlace", name=name, cost_metric="pin_manhattan_m", wide_cap=cap,
                               source_sha256=digest(source), bank_sha256=text_digest(bank))

    bank = EVIDENCE / "tap-sensitivity-plan.json"
    historical = json.loads((EVIDENCE / "tap-sensitivity.json").read_bytes())["cases"]
    for entry in json.loads(bank.read_bytes())["cases"]:
        d = entry["domain"]
        chips = sorted(d["chiplets"], key=lambda c: c["id"])
        ids = [c["id"] for c in chips]
        sizes = np.array([[c["core_width_um"], c["core_height_um"]] for c in chips], float)
        side = d["interposer_side_um"]
        p = Problem(d["name"], tuple(f"die_{i}" for i in ids), sizes, np.array([c["power_w"] for c in chips]),
                    (side, side), np.empty((0, 2), int), np.empty((0, 2, 2)))
        expanded = replace(p, size_um=sizes + 2 * np.array([c["bump_ring_um"] for c in chips])[:, None])
        weights = np.array(d["connection_wire_demands"])
        reference = next(item["rows"] for item in historical if item["case"] == p.name)
        designs = []
        for i, placement in enumerate(entry["placements"][:6]):
            pose = sorted(placement, key=lambda c: c["id"])
            assert [c["id"] for c in pose] == ids
            xy = np.array([[c["centre_x_um"], c["centre_y_um"]] for c in pose], float)
            layout = Layout(xy, np.array([c["rotation_deg"] for c in pose]))
            assert is_legal(expanded, layout, GAP_UM)
            distance = np.abs(xy[:, None] - xy[None, :]).sum(axis=2) / 1000
            cost = float(np.sum(distance * weights) / weights.sum())
            assert reference[i]["index"] == i and abs(cost - reference[i]["centre_span_mm"]) < 1e-8
            designs.append((i, layout, cost))
        yield p, designs, dict(family="TAP-2.5D", name=p.name, cost_metric="demand_weighted_centre_mm",
                               wide_cap=max(v[2] for v in designs), bank_sha256=text_digest(bank))


def build(p, layout, sites, boundary):
    mean = 0.25 * p.power_w
    mean[sites] = 0.6 * p.power_w[sites]
    data = [thermal_case_data(replace(p, power_w=w), layout, GAP_UM, GRID)
            for w in (mean, *np.eye(p.count)[sites])]
    for item in data:
        if boundary == "half_top":
            item["thermal"]["top_h_w_m2k"] *= 0.5
    g, cap, powers, sink, nodes, ambient = package_model(data)
    assert powers.min() >= 0 and cap.min() > 0
    np.testing.assert_allclose(powers.sum(0), [mean.sum(), 1, 1, 1, 1], atol=1e-7, rtol=0)
    return g, cap, powers, sink, nodes, ambient


def directions():
    unit = np.eye(4)
    pairs = {f"pair-{i}{j}": unit[i] - unit[j] for i, j in combinations(range(4), 2)}
    splits = {}
    for j in (1, 2, 3):
        split = -np.ones(4)
        split[[0, j]] = 1
        splits[f"split-0{j}"] = split
    return pairs, splits


def peak_tests(mean, response, directions, watts):
    labels = list(directions)
    signals = response @ np.stack([directions[k] for k in labels], axis=1)
    peaks = (mean[:, None] + watts * np.abs(signals)).max(axis=0)
    return dict(zip(labels, map(float, peaks)))


def dc_fields(model, amplitude):
    g, _, powers, sink, nodes, ambient = model
    field = splu(g.tocsc(), permc_spec="MMD_AT_PLUS_A").solve(powers)
    for col in range(powers.shape[1]):
        checked_solution(g, powers[:, col], sink, field[:, col])
    mean = ambient + field[nodes, 0]
    response = field[nodes, 1:]
    assert response.min() >= 0
    gain = response.sum(1)
    pairs, splits = directions()
    trials = {}
    for f in FRACTIONS:
        watts = f * amplitude
        trials[str(f)] = dict(upper_c=float((mean + watts * gain).max()),
                              slow_c=peak_tests(mean, response, pairs | splits, watts))
    return mean, gain, dict(mean_peak_c=float(mean.max()), levels=trials)


def mean_field(model):
    g, _, powers, sink, nodes, ambient = model
    steady = splu(g.tocsc(), permc_spec="MMD_AT_PLUS_A").solve(powers[:, 0])
    checked_solution(g, powers[:, 0], sink, steady)
    return steady[nodes] + ambient


def harmonic_fields(model, period):
    g, cap, powers, sink, nodes, _ = model
    iw = 2j * np.pi / period
    admittance = g + diags(iw * cap)
    fields = splu(admittance.tocsc(), permc_spec="MMD_AT_PLUS_A").solve(powers[:, 1:])
    # For each per-watt input, complex stored and removed power must sum to 1 W.
    balance = float(np.abs(iw * (cap @ fields) + sink @ fields - 1).max())
    residual = float(np.abs(admittance @ fields - powers[:, 1:]).max())
    assert balance < 1e-6 and residual < 1e-8
    return fields[nodes], balance, residual


def ac_challenge(model, amplitude):
    mean = mean_field(model)
    pair, _ = directions()
    signals = dict(pair, quadrature=pair["pair-01"] + 1j * pair["pair-23"])
    scores = {str(f): {} for f in FRACTIONS}
    balance, residual = 0.0, 0.0
    for period in PERIODS:
        fields, b, r = harmonic_fields(model, period)
        balance, residual = max(balance, b), max(residual, r)
        for f in FRACTIONS:
            peaks = peak_tests(mean, fields, signals, f * amplitude)
            scores[str(f)].update({f"{period}s/{k}": v for k, v in peaks.items()})
    return dict(levels=scores, max_harmonic_balance_per_w=balance, max_node_residual_per_w=residual)


def storage_counterexample():
    """Identical steady measurements, opposite answers about whether one design suffices."""
    conductance = np.array([1., 1., 10., 10.])
    mean_power = np.array([5., 5., 2., 2.])
    steady = mean_power / conductance
    capacities = {"base": [.005, .05, 1, 1], "cold_change": [.005, .05, 2, 1],
                  "hot_swap": [.05, .005, 1, 1]}
    period = 0.1
    omega = 2 * np.pi / period
    pairs = ([1., 0., -1., 0.], [0., 1., 0., -1.])
    peaks = {}
    integration_error = 0.
    for name, c in capacities.items():
        c = np.array(c)
        peaks[name] = []
        for weight in pairs:
            weight = np.array(weight)
            response = weight / (conductance + 1j * omega * c)
            peak = float((steady + np.abs(response)).max())
            peaks[name].append(peak)
            def derivative(t, rise):
                return (mean_power + weight * np.cos(omega*t) - conductance * rise) / c
            # Start from the mean and let transients decay, independent of the phasor initial state.
            times = np.linspace(30*period, 31*period, 1501)
            sol = solve_ivp(derivative, (0, times[-1]), steady, t_eval=times, rtol=1e-9, atol=1e-11)
            assert sol.success
            integration_error = max(integration_error, abs(float(sol.y.max()) - peak))
    assert integration_error < 1e-5
    return dict(conductance_w_k=conductance.tolist(), mean_power_w=mean_power.tolist(), capacities_j_k=capacities,
                period_s=period, weights_w=pairs, peaks_rise_k=peaks, ode_peak_difference_k=integration_error,
                indistinguishable_dc_conflict_lower_k=float(regret(np.array([peaks["base"], peaks["hot_swap"]]).T)
                                                            .max(axis=0).min()))


def regret(peaks):
    x = np.array(peaks)
    return x - x.min(axis=1, keepdims=True)


def predict_pool(pool, costs, fields, summaries, amplitude, fraction):
    means = [summaries[g]["mean_peak_c"] for g in pool]
    level = str(fraction)
    uppers = [summaries[g]["levels"][level]["upper_c"] for g in pool]
    _, upper_loss = worst_regret_bounds([means], [uppers])
    tests = {"mean": means}
    for f in FRACTIONS:
        if f > fraction:
            continue
        for k in summaries[pool[0]]["levels"][str(f)]["slow_c"]:
            tests[f"{f}/{k}"] = [summaries[g]["levels"][str(f)]["slow_c"][k] for g in pool]
    witness_loss = regret(list(tests.values()))
    lower_loss = witness_loss.max(axis=0)
    assert np.all(upper_loss + 1e-8 >= lower_loss)
    designs = {}
    for j, g in enumerate(pool):
        ceiling = min((v for i, v in enumerate(means) if i != j), default=np.inf) + EPS_K
        radius = guaranteed_amplitude(*fields[g], ceiling, amplitude)
        worst = int(witness_loss[:, j].argmax())
        designs[g] = dict(upper_k=float(upper_loss[j]), lower_k=float(lower_loss[j]), radius_w=radius,
                          worst_witness=list(tests)[worst], competitor=pool[int(np.argmin(list(tests.values())[worst]))])
    chosen = min(pool, key=lambda g: (designs[g]["upper_k"], costs[g], g))
    lo, hi = float(min(lower_loss)), float(min(upper_loss))
    status = "certified" if hi <= EPS_K else "conflict" if lo > EPS_K + 1e-8 else "unresolved"
    return dict(status=status, chosen=chosen, lower_k=lo, upper_k=hi, designs=designs,
                radius_w=max(v["radius_w"] for v in designs.values() if v["radius_w"] is not None))


def challenge_pool(pool, costs, observed, forecasts, pred):
    level = str(pred["fraction"])
    labels = observed[pool[0]]["levels"][level].keys()
    peaks = np.array([[observed[g]["levels"][level][k] for g in pool] for k in labels])
    for j, g in enumerate(pool):
        assert np.all(peaks[:, j] >= forecasts[g]["mean_peak_c"] - 1e-8)
        assert np.all(peaks[:, j] <= forecasts[g]["levels"][level]["upper_c"] + 1e-8)
    losses = regret(peaks).max(axis=0)
    eligible = [g for g, loss in zip(pool, losses) if loss <= EPS_K]
    chosen_loss = float(losses[pool.index(pred["chosen"])])
    assert chosen_loss <= pred["designs"][pred["chosen"]]["upper_k"] + 1e-8
    shortest = min(eligible, key=lambda g: (costs[g], g), default=None)
    return dict(locked_loss_k=chosen_loss, sample_minimax_k=float(min(losses)), shortest_layout=shortest,
                shortest_cost=costs.get(shortest), within_tolerance=len(eligible))


def run_case(problem, designs, meta, prediction, *, unresolved_only=False):
    sites = sorted(range(problem.count), key=lambda k: (-problem.power_w[k], k))[:4]
    assert len(sites) == 4
    amplitude = float(0.4 * min(problem.power_w[sites]))
    costs = {str(i): cost for i, _, cost in designs}
    budgets = {"wide": meta["wide_cap"]}
    if len(costs) >= 2:
        budgets["tight"] = sorted(costs.values())[1]
    result = dict(**meta, costs=costs, amplitude_w=amplitude, chiplets=problem.count,
                  sites=[problem.names[i] for i in sites], budgets=budgets, conditions={})
    if prediction is not None:
        for k in result.keys() - {"conditions"}:
            assert result[k] == prediction[k]
    if not designs:
        return result
    for boundary in ("nominal", "half_top"):
        rows, fields = {}, {}
        needed = set(costs)
        if unresolved_only:
            needed = {g for q in prediction["conditions"][boundary]["groups"]
                      if q["status"] == "unresolved" for g in q["pool"]}
        for i, layout, _ in designs:
            g = str(i)
            if g not in needed:
                continue
            model = build(problem, layout, sites, boundary)
            if prediction is None:
                mean, gain, rows[g] = dc_fields(model, amplitude)
                fields[g] = (mean, gain)
            else:
                rows[g] = ac_challenge(model, amplitude)
        groups = []
        for budget, cap in budgets.items():
            pool = [g for g, cost in costs.items() if cost <= cap]
            for frac in FRACTIONS:
                info = dict(budget=budget, pool=pool, fraction=frac)
                if prediction is None:
                    out = predict_pool(pool, costs, fields, rows, amplitude, frac)
                else:
                    prior = prediction["conditions"][boundary]
                    fixed = next(q for q in prior["groups"] if q["budget"] == budget and q["fraction"] == frac)
                    assert fixed["pool"] == pool
                    if unresolved_only and fixed["status"] != "unresolved":
                        continue
                    out = challenge_pool(pool, costs, rows, prior["rows"], fixed)
                groups.append(dict(**info, **out))
        result["conditions"][boundary] = dict(rows=rows, groups=groups)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="Directory of imported ATPlace JSON files")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--challenge", type=Path, help="Read frozen DC predictions and run held-out waveforms")
    parser.add_argument("--unresolved-only", action="store_true", help="Only challenge groups unresolved by DC")
    args = parser.parse_args()
    predictions = None
    if args.unresolved_only and args.challenge is None:
        parser.error("--unresolved-only needs a frozen --challenge file")
    if args.challenge:
        evidence = json.loads(args.challenge.read_bytes())
        assert evidence["protocol"] == PROTOCOL and evidence["stage"] == "predict"
        predictions = {row["name"]: row for row in evidence["cases"]}
    result = dict(protocol=PROTOCOL, stage="predict" if predictions is None else "challenge", grid=GRID,
                  gap_um=GAP_UM, tolerance_k=EPS_K, periods_s=PERIODS, cases=[])
    if predictions is not None:
        result["prediction_sha256"] = text_digest(args.challenge)
        if args.unresolved_only:
            result["unresolved_only"] = True
        else:
            result["storage_control"] = storage_counterexample()
    for problem, designs, meta in cases(args.cases):
        frozen = None if predictions is None else predictions[meta["name"]]
        result["cases"].append(run_case(problem, designs, meta, frozen, unresolved_only=args.unresolved_only))
        print(meta["name"], len(designs), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
