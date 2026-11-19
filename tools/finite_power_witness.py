"""Construct finite-period physical witnesses for DC conflicts missed by the blind frequencies."""

import argparse
import json
from pathlib import Path

import numpy as np

from power_uncertainty import (
    EPS_K, FRACTIONS, PERIODS, build, cases, directions, harmonic_fields, mean_field, peak_tests, text_digest,
)


SLOW = (1.37, 13.7, 137., 1370.)


def compare(pool, samples, allowed):
    tests = [s for s in samples if s["fraction"] <= allowed]
    values = np.array([[s["peaks_c"][g] for g in pool] for s in tests])
    losses = values - values.min(axis=1)[:, None]
    witnesses = {}
    for j, g in enumerate(pool):
        i = int(losses[:, j].argmax())
        rival = int(values[i].argmin())
        witnesses[g] = dict(period_s=tests[i]["period_s"], fraction=tests[i]["fraction"], signal=tests[i]["signal"],
                            rival=pool[rival], peak_c=float(values[i, j]), rival_c=float(values[i, rival]),
                            loss_k=float(losses[i, j]))
    return dict(lower_k=float(losses.max(axis=0).min()), witnesses=witnesses)


def sample(models, means, pool, period, amplitude, signals):
    rows = {(f, label): {} for f in FRACTIONS for label in signals}
    for g in pool:
        field, _, _ = harmonic_fields(models[g], period)
        for frac in FRACTIONS:
            for label, peak in peak_tests(means[g], field, signals, frac * amplitude).items():
                rows[frac, label][g] = peak
    return [dict(period_s=period, fraction=f, signal=k, peaks_c=v) for (f, k), v in rows.items()]


def run(problem, designs, meta, prior, audit):
    result = []
    sites = sorted(range(problem.count), key=lambda k: (-problem.power_w[k], k))[:4]
    pair, splits = directions()
    signals = pair | splits
    for boundary, source in prior["conditions"].items():
        blind = audit["conditions"][boundary]["groups"]
        missed = []
        for p, t in zip(source["groups"], blind, strict=True):
            assert (p["budget"], p["fraction"], p["pool"]) == (t["budget"], t["fraction"], t["pool"])
            if p["status"] == "conflict" and t["sample_minimax_k"] <= EPS_K:
                missed.append(p)
        if not missed:
            continue
        needed = {g for p in missed for g in p["pool"]}
        models = {str(i): build(problem, layout, sites, boundary) for i, layout, _ in designs if str(i) in needed}
        means = {g: mean_field(m) for g, m in models.items()}
        base = dict(period_s=None, fraction=0., signal="mean", peaks_c={g: float(y.max()) for g, y in means.items()})
        matched = [base]
        for period in PERIODS:
            matched += sample(models, means, needed, period, prior["amplitude_w"], signals)
        pending = []
        for p in missed:
            short = compare(p["pool"], matched, p["fraction"])
            row = dict(case=meta["name"], cooling=boundary, budget=p["budget"], fraction=p["fraction"],
                       amplitude_w=p["fraction"] * prior["amplitude_w"], pool=p["pool"], matched_fast=short,
                       first_successful_period_s=None, slow_history=[])
            pending.append(row)
            result.append(row)
        history = [base]
        for period in SLOW:
            needed = {g for row in pending for g in row["pool"]}
            if not needed:
                break
            history += sample(models, means, needed, period, prior["amplitude_w"], signals)
            for row in pending:
                q = compare(row["pool"], history, row["fraction"])
                row["slow_history"].append(dict(period_s=period, lower_k=q["lower_k"]))
                row["slow_witnesses"] = q["witnesses"]
                if q["lower_k"] > EPS_K + 1e-8:
                    row["first_successful_period_s"] = period
            pending = [row for row in pending if row["first_successful_period_s"] is None]
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--challenge", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    pred = json.loads(args.predictions.read_bytes())
    aud = json.loads(args.challenge.read_bytes())
    assert aud["prediction_sha256"] == text_digest(args.predictions)
    rows = []
    for (problem, designs, meta), p, t in zip(cases(args.cases), pred["cases"], aud["cases"], strict=True):
        assert meta["name"] == p["name"] == t["name"]
        rows += run(problem, designs, meta, p, t)
    data = dict(predictions_sha256=text_digest(args.predictions), challenge_sha256=text_digest(args.challenge),
                periods_s=SLOW, groups=rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print("physical groups", len(rows))


if __name__ == "__main__":
    main()
