# Separate electrical admission and incremental timing costs

The Chat review correctly identified that the old `timing_temperature_cost`
used the routing-stage minimum as its baseline. This combines electrical-model
admission and timing constraints. The new report has `cost_definition_version=2`
and names both endpoints of every cost.

For a fixed operating profile and mode, let R be the minimum peak temperature
over routing-feasible designs, E over electrically admitted designs, and T
over timing-feasible designs. Here electrical admission means the current
evaluator returned `analyzed`; it is not real Pad or package qualification.

| Report field | Difference | Interpretation |
|---|---|---|
| `electrical_temperature_cost` | E − R | Electrical-model admission cost |
| `timing_temperature_cost` | T − E | Incremental timing-constraint cost |
| `combined_electrical_timing_temperature_cost` | T − R | Combined cost, preserving the previous routing-baseline quantity |

The renderer displays all three. The previous frozen reports retain their
historical semantics; new consumers must inspect `cost_definition_version`
and `baseline_stage`/`target_stage`. Do not silently compare the old and new
`timing_temperature_cost` fields as if their definitions were identical.

The admitted sets are nested, so the three exact costs are nonnegative and
the first two sum to the third. The same arithmetic applies to minima over
the same evaluated ledger. However, a difference of two observed witness
temperatures is not automatically an exact global cost. Route-search failures,
timeouts and model-domain rejection do not prove the absence of another route.

Each cost still distinguishes evaluated-subset differences from certified
exact values. Exact cost requires certified endpoint optima. With only the
complete-domain geometric lower bound L and target witness U, the conservative
bound remains [0, U−L]. It is deliberately not tightened using the observed
baseline minimum, which is an upper bound rather than a proved lower bound.
Missing endpoint witnesses or missing domain coverage remain explicit unknowns.

## Verification

Two constructed tests expose the former ambiguity: a 30 C routed candidate
outside electrical admission, a 33 C analyzed candidate violating timing,
and a 35 C timing-feasible candidate yield subset costs 3 K, 2 K and 5 K.
They do not certify positive global costs. A separate timeout case verifies
that the observed combined gap is not charged to incremental timing and does
not become a proof.

The frozen 12-layout benchmark and additional witnesses were reprocessed with
their existing full input/artifact/runtime guards. All 5,248 saved timing
paths were covered by the evidence checks. In all four operating profiles,
both reference and feedback modes still have exact electrical, incremental
timing and combined costs of zero within the declared finite numerical model.
No native electrical or thermal simulation was rerun for this accounting fix.

[Updated compact evidence](evidence/local-integrated-decision-cost-v2.json)
records the regenerated proof summaries. The full 223-test suite and documented
two-chiplet CLI passed locally. Physical calibration, full-fabric uniform
temperature controls, multi-layout hot comparisons and receiver constraints
remain outside this fix; Goal 01 is still incomplete.
