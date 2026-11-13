# Case1: necessary routing admission and bounded thermal-boundary check

Start: successful fetch of origin/main at `6810a7269ccdebbb2279aae8d745b0beb4965a6a`,
clean main, no remote additions. Local execution only. Chat remains deferred by
the user's decision. This stage does not add seeds, optimizer heuristics, or a
calibration campaign.

## 1. Necessary routing conditions

Retain each of the 3,168 independent two-pin source nets and all 6,336 exact
rotated terminal coordinates. Reuse the earlier TAP graph's **resource assumptions**,
not its invented-for-TAP bump ring: 1 mm bins, one horizontal and one vertical
signal layer, 2 um track pitch (500 slots per bin boundary), and no blocked metal
under dies. The 1 um wire width / 2 um pitch reference is Table 2 of
[Coskun et al., ICCAD 2018](https://people.bu.edu/joshi/files/interposer-nw-iccad-2018.pdf).
The two signal layers, continuous ideal reference planes, and 2 um terminal
access pitch are our assumptions, not an ATPlace or foundry stack. The access
bound is (1000/2)^2 ideal sites per bin; it does not establish a physical Pad map.
No pitch/capacity sweep may be used to manufacture a binding constraint.

The 42 x 42 mm carrier has 42 x 42 bins. Pins map into half-open bins, with the
outer maximum assigned to the last bin. For every full vertical/horizontal cut,
count nets with endpoints on opposite sides; capacity is the sum of the crossed
track edges. For each bin perimeter, count nets with exactly one endpoint inside;
capacity includes only existing neighboring edges (less at carrier boundaries).
Count both directions together. Nets wholly inside a bin do not consume escape
capacity but their two independent terminals still consume access sites.

Demand greater than capacity is a certificate of failure **in this declared
graph**. Passing these selected cuts is only a necessary condition: no path or
track/via assignment is constructed. Detailed pin escape, bump geometry, same-layer
spacing, PDN/clock resource reservations, return connectivity, SI and timing are
unresolved. A die body does not become an interposer obstacle. Do not fabricate a
maximum wire reach without a driver/channel/clock specification.

The new evaluator performs this gate before the thermal solve and before thermal
cache reuse, so a half-turn cannot inherit another orientation's routing result.
Historical frozen runners remain unchanged. This stage applies the gate to the
existing F archive, not a claimed new adaptive search. If any row is rejected,
report the filtered archive and defer a new online trajectory; do not claim
post-filtering reproduces a constrained search. If all rows pass, filtering leaves
the original 48-query trajectory and both constrained joint winners unchanged.

## 2. Single-seed archive acceptance, then five fixed final candidates

Use seed 2026111200, F's 16 initial + 32 online thermal queries, and original
L0=73.840208806 m / T0=107.45047721858577 C. Reuse the saved nominal thermal
responses only after exact physical-input hash matching. This saves 48 repeat
solves. Recompute actual pin distance, all admission checks and both filtered
joint metrics. Runtime and screen counts are auxiliary, not quality improvements.

Before any new thermal query, freeze these five layouts: original base, B primary
winner (best historical primary point), D primary winner (joint tradeoff), E
primary winner (F's direct baseline), and F primary winner (current selection).
Keep complete poses, nominal temperatures and pin distances. Apply the same
routing gate to all of them. These are fixed candidates, not a newly sampled
optimization population; C and secondary winners are outside this bounded check.

## 3. Three perturbations, at most 15 new local thermal solves

For every admitted finalist independently use:

- `half_h`: top h multiplied by 0.5;
- `double_h`: top h multiplied by 2;
- `tim_contact`: nominal h, add 5e-6 m2 K/W at the TIM/spreader interface.

These are declared stress scenarios, **not measurement-derived uncertainty
intervals**. The added interface resistance equals the modeled TIM's own
t/k = 20e-6 / 4 = 5e-6 m2 K/W, providing a modest, interpretable scale without
pretending it is measured. A continuous full-area interface is assumed. Leave
all powers (780 W), materials, die poses, pin distances, mesh policy, side/bottom
adiabatic boundaries, 200 x 200 mm top area and ambient (45 C) fixed.

Nominal convection resistance is 0.009 K/W, hence half/double h gives 0.018 /
0.0045 K/W. Global surface-mean temperatures must be consistent with
45 + 780/(h*0.04). Contact resistance does not change this global boundary balance.
Use the existing half-cell series assembly and original conservation/passivity
checks. Check hotter peaks for weaker top cooling and cooler peaks for stronger
cooling. Do not reuse thermal responses across scenarios. No tighter mesh study.

Report each candidate's actual T and fixed L, cooling versus the base **under the
same boundary**, the five-candidate ordering and pairwise ordering changes.
Keep L0 fixed. The original absolute T0, if referenced, stays fixed; never silently
renormalize it to make a candidate feasible. Do not claim scenario-specific global
optima: these checks neither reoptimize nor establish robustness outside the
tested boundary family. Retain negative results and small differences as such.

## Reproduction

From the repository with the Windows environment loaded:

```powershell
python tools/run_atplace_routing_boundary.py --freeze
python tools/run_atplace_routing_boundary.py --screen --output results/atplace-case1-routing-screen-v1.json
python tools/run_atplace_routing_boundary.py --sensitivity --screen-result results/atplace-case1-routing-screen-v1.json --hits ../HiTS --output results/atplace-case1-boundary-v1.json
```

Run focused gate and scenario tests, the full repository suite, and documented
two-chiplet CLI before the implementation milestone. Push the frozen protocol /
plan before the new queries, then push the bounded results and Overall update.
