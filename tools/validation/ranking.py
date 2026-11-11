"""Constraint-first summaries; a score tradeoff does not establish necessity."""

import itertools

PRINTED_SLACK_TOLERANCE_NS = 2e-6


def admissible(rows):
    return [r for r in rows if r["timing_status"] == "analyzed"]


def conflicts(rows, slack_tolerance_ns=PRINTED_SLACK_TOLERANCE_NS):
    pairs = []
    for a, b in itertools.combinations(admissible(rows), 2):
        dt, ds = a["peak_c"] - b["peak_c"], a["worst_slack_ns"] - b["worst_slack_ns"]
        if (
            abs(dt) > a["mesh_peak_change_k"] + b["mesh_peak_change_k"]
            and abs(ds) > slack_tolerance_ns
            and dt * ds > 0
        ):
            pairs.append(
                dict(
                    a=a["id"],
                    b=b["id"],
                    temperature_difference_k=dt,
                    margin_difference_ns=ds,
                    same_tx_y=a["placement_mm"]["tx"]["y"]
                    == b["placement_mm"]["tx"]["y"],
                )
            )
    return pairs


def pareto_ids(rows, slack_tolerance_ns=0):
    legal = admissible(rows)

    def dominates(a, b):
        return (
            a["peak_c"] <= b["peak_c"]
            and a["worst_slack_ns"] >= b["worst_slack_ns"] - slack_tolerance_ns
            and (
                a["peak_c"] < b["peak_c"]
                or a["worst_slack_ns"] > b["worst_slack_ns"] + slack_tolerance_ns
            )
        )

    return [
        b["id"] for b in legal if not any(a is not b and dominates(a, b) for a in legal)
    ]


def summarize(rows):
    pool = admissible(rows)
    feasible = [r for r in pool if r["setup_slack_ns"] >= 0 and r["hold_slack_ns"] >= 0]
    thermal = min(pool, key=lambda r: (r["peak_c"], r["id"])) if pool else None
    constrained = (
        min(feasible, key=lambda r: (r["peak_c"], r["id"])) if feasible else None
    )
    pairs = conflicts(pool)
    return dict(
        candidate_count=len(rows),
        geometrically_and_electrically_legal_count=len(pool),
        timing_feasible_count=len(feasible),
        timing_infeasible_count=len(pool) - len(feasible),
        thermal_optimum_before_timing_filter=thermal["id"] if thermal else None,
        thermal_optimum_is_timing_feasible=(
            (thermal["setup_slack_ns"] >= 0 and thermal["hold_slack_ns"] >= 0)
            if thermal
            else None
        ),
        constrained_thermal_optimum=constrained["id"] if constrained else None,
        timing_constraint_thermal_penalty_k=(
            (constrained["peak_c"] - thermal["peak_c"]) if constrained else None
        ),
        setup_range_ns=(
            [
                min(r["setup_slack_ns"] for r in pool),
                max(r["setup_slack_ns"] for r in pool),
            ]
            if pool
            else None
        ),
        hold_range_ns=(
            [
                min(r["hold_slack_ns"] for r in pool),
                max(r["hold_slack_ns"] for r in pool),
            ]
            if pool
            else None
        ),
        pareto_ids_at_raw_report_precision=pareto_ids(pool),
        pareto_ids_with_printed_slack_tolerance=pareto_ids(
            pool, PRINTED_SLACK_TOLERANCE_NS
        ),
        conflict_pairs=pairs if len(pool) >= 2 else None,
        conflict_count=len(pairs) if len(pool) >= 2 else None,
        conflicts_with_same_tx_y=(
            sum(p["same_tx_y"] for p in pairs) if len(pool) >= 2 else None
        ),
        conflicts_with_different_tx_y=(
            sum(not p["same_tx_y"] for p in pairs) if len(pool) >= 2 else None
        ),
        conflict_count_above_1ps=(
            len(conflicts(pool, 0.001)) if len(pool) >= 2 else None
        ),
        effect_size_filter_scope="1 ps is a diagnostic threshold, not physical uncertainty",
        pair_scope="Shared design/model/placements; pair counts are not independent replicates",
    )


def common_cohort(policies):
    populated = {
        p: admissible(rows) for p, rows in policies.items() if admissible(rows)
    }
    ids = (
        set.intersection(*({r["id"] for r in rows} for rows in populated.values()))
        if populated
        else set()
    )
    return dict(
        included_policies=list(populated),
        excluded_empty_policies=sorted(set(policies) - set(populated)),
        layout_ids=sorted(ids),
        summaries={
            p: summarize([r for r in rows if r["id"] in ids])
            for p, rows in populated.items()
        },
    )
