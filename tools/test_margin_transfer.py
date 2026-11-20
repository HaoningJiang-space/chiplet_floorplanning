"""Controlled test of power-scaled thermal margins across fixed-pin synthetic graphs."""

import argparse
from dataclasses import replace
from itertools import product
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import is_legal
from chiplet_floorplanning.placement.cooled_sheet import CooledSheet, footprint
from chiplet_floorplanning.placement.problem import Layout, Problem
from chiplet_floorplanning.placement.thermal import solve
from common_relocation import CENTRES, FOUR
from direct_relocation import physical_cost
from relocation_contact import contact_model


SEED = 20261119
SLOTS = np.array([(7 + x * 13, 7 + y * 13) for y in range(2) for x in range(4)]) * 1000.
START = np.random.default_rng(SEED).permutation([0, 2, 5, 7])
VACANT = [1, 3, 4, 6]
GRAPHS = dict(chain=[(0, 1), (1, 2), (2, 3)],
              ring=[(0, 1), (1, 2), (2, 3), (3, 0)],
              star=[(0, 1), (0, 2), (0, 3)])
POWERS = dict(uniform=np.full(4, 2.05), heterogeneous=2.05*np.array([.4, .8, 1.2, 1.6]))


def geometry(slots):
    return Layout(SLOTS[list(slots)], np.zeros(4, int))


def unit_fields(problem):
    sheets = [CooledSheet(problem, np.asarray(CENTRES[b])) for b in FOUR]
    response = []
    for sh in sheets:
        rows = []
        for xy in SLOTS:
            centre = xy/1000 + sh.carrier_offset
            watts = footprint(sh.edges, centre-4., centre+4.)/64.
            rows.append(sh.temperatures(watts).ravel())
        response.append(rows)
    return sheets, np.array(response)


def package_peaks(problem, slots):
    values = []
    for b in FOUR:
        model = contact_model(problem, geometry(slots), 64, np.array(CENTRES[b], dtype=float))
        source = "Synthetic four-die slot test; declared finite-volume package"
        model["thermal"]["provenance"] = source
        for die in model["chiplets"]:
            for block in die["blocks"]:
                block["provenance"] = source
        summary, _, _ = solve(model, node_limit=450000)
        values.append(summary["peak_power_layer_c"])
    return np.array(values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    p = Problem("four_slot_test", tuple(f"die_{i}" for i in range(4)), np.full((4, 2), 8000.),
                POWERS["uniform"], (53000., 27000.), np.array(GRAPHS["chain"]), np.zeros((3, 2, 2)))
    _, response = unit_fields(p)
    feasible_geometry = [tuple(map(int, state)) for state in product(*[[s, *VACANT] for s in START])
                         if is_legal(p, geometry(state), 100)]
    initial = tuple(map(int, START))
    result = dict(seed=SEED, slots_um=SLOTS.tolist(), start=initial, vacant=VACANT, graphs=GRAPHS,
                  powers_w={k:v.tolist() for k,v in POWERS.items()}, basis_solves=len(FOUR)*len(SLOTS),
                  assignments=5**4, geometry_legal=len(feasible_geometry), cases={})
    for power_name, watts in POWERS.items():
        # Changing the pin graph only changes the admissible layouts in this
        # fixed-power experiment. Compute temperatures once per power vector.
        def peaks(state):
            field = sum(w * response[:, s] for w, s in zip(watts, state))
            return field.max(axis=1)

        root_peaks = peaks(initial)
        change = {s: root_peaks-peaks(s) for s in feasible_geometry}
        solo = {}
        for i in range(4):
            for site in [initial[i], *VACANT]:
                state = list(initial)
                state[i] = site
                solo[i, site] = float(min(change[tuple(state)]))
        additive = {s:sum(solo[i, site] for i, site in enumerate(s)) for s in feasible_geometry}
        moved = {s:sum(a != b for a,b in zip(initial,s)) for s in feasible_geometry}
        problem = replace(p, power_w=watts)
        root_3d = package_peaks(problem, initial)
        solved_3d = {initial:root_3d}
        direct = [CooledSheet(problem, np.array(CENTRES[b])) for b in FOUR]
        old_direct = np.array([sh.peak(geometry(initial)) for sh in direct])
        for graph, edges in GRAPHS.items():
            wired = replace(problem, pin_chip=np.array(edges), pin_offset_um=np.zeros((len(edges),2,2)))
            wire = {s:physical_cost(wired, geometry(s), None) for s in feasible_geometry}
            legal = [s for s in feasible_geometry if wire[s] <= wire[initial] + 1e-12]
            def best(states, value):
                return min(states, key=lambda s:(-round(float(value(s)),10), wire[s], moved[s], s))

            def item(state):
                return dict(slots=state, gain_k=float(min(change[state])), by_boundary_k=change[state].tolist(),
                            wire_m=wire[state], moved=moved[state])

            rows = []
            winners = []
            for k in range(1,5):
                available = [s for s in legal if moved[s] <= k]
                joint = best(available, lambda s:min(change[s]))
                scalar = best(available, additive.get)
                winners.append(joint)
                rows.append(dict(k=k, joint=item(joint), single_sum=item(scalar)))
            selected = winners[-1]
            solo_components = [dict(die=i, from_slot=initial[i], to_slot=site,
                                    single_worst_k=solo[i,site])
                               for i,site in enumerate(selected) if site != initial[i]]
            # Retrospective inversion: reuse every attainable wire breakpoint.
            # No topology-specific cap or new thermal queries enter this curve.
            by_cap = []
            for cap in sorted({round(wire[s],12) for s in legal}):
                candidates = [s for s in legal if wire[s] <= cap+1e-12]
                by_cap.append(dict(cap_m=cap, best=item(best(candidates, lambda s:min(change[s])))))
            if selected not in solved_3d:
                solved_3d[selected] = package_peaks(problem, selected)
            checked = list(dict.fromkeys(s for s in [*winners, *sorted(legal)] if s != initial))[:4]
            assert len(checked) == 4
            error = 0.
            for state in checked:
                actual = np.array([sh.peak(geometry(state)) for sh in direct])
                error = max(error, float(max(abs((old_direct-actual)-change[state]))))
            assert error < 1e-8
            result["cases"][f"{graph}_{power_name}"] = dict(cap_m=wire[initial], legal=len(legal),
                cardinalities=rows, boundary_only={b:item(best(legal,lambda s:change[s][i])) for i,b in enumerate(FOUR)},
                selected_package_cooling_k=(root_3d-solved_3d[selected]).tolist(),
                joint_components=solo_components, retrospective_wire_curve=by_cap,
                direct_check_slots=checked, direct_max_error_k=error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n", encoding="utf8", newline="\n")


if __name__ == "__main__":
    main()
