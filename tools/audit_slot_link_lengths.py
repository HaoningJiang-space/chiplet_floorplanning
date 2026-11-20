"""Check the longest individual link in the same finite row/column placement family."""

import argparse
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement.geometry import pin_manhattan_um, rotate
from chiplet_floorplanning.placement.wire_slots import _axis_costs
from scale_slot_margin import problem


def audit(p, start, joint):
    x, col = np.unique(start.centre_um[:, 0], return_inverse=True)
    y, row = np.unique(start.centre_um[:, 1], return_inverse=True)
    pins = p.pin_chip
    offset = rotate(p.pin_offset_um, start.rotation_deg[pins])
    delta = offset[:, 0] - offset[:, 1]
    families = []
    for axis, coords, group in ((0, x, col), (1, y, row)):
        orders, total_m = _axis_costs(coords, group, pins, delta[:, axis])
        families.append((orders, total_m))
    (xo, wx), (yo, wy) = families
    cap = joint["cap_m"] + 1e-9
    baseline_max = float(pin_manhattan_um(p, start).max()/1000)
    slot = np.empty((len(y), len(x)), int)
    slot[row, col] = np.arange(p.count)
    maps = {}
    admissible = 0
    admissible_both = 0
    for i in np.flatnonzero(wx <= cap - wy.min()):
        xx = x[xo[i, col]]
        dx = abs(xx[pins[:, 0]] - xx[pins[:, 1]] + delta[:, 0])
        js = np.flatnonzero(wy <= cap - wx[i])
        yy = y[yo[js][:, row]]
        lengths = dx + abs(yy[:, pins[:, 0]] - yy[:, pins[:, 1]] + delta[:, 1])
        np.testing.assert_allclose(lengths.sum(axis=1)/1e6, wx[i]+wy[js], rtol=0, atol=1e-11)
        for j, maximum in zip(js, lengths.max(axis=1)/1000):
            perm = slot[yo[j, row], xo[i, col]]
            power = np.empty_like(p.power_w)
            power[perm] = p.power_w
            hot = tuple(np.flatnonzero(power == p.power_w.max()).tolist())
            maps[hot] = min(maps.get(hot, np.inf), maximum)
            admissible += 1
            admissible_both += int(maximum <= baseline_max + 1e-9)
    assert admissible == joint["counts"]["feasible_identity_assignments"]
    assert len(maps) == joint["counts"]["distinct_feasible_power_maps"]
    start_hot = tuple(np.flatnonzero(p.power_w == p.power_w.max()).tolist())
    kept = [hot for hot, value in maps.items() if value <= baseline_max + 1e-9]
    return dict(start_longest_mm=baseline_max, identity_count=admissible,
                identity_count_at_both_caps=admissible_both,
                thermal_patterns_at_both_caps=len(kept), only_start_power_map=kept == [start_hot],
                selected_pattern_min_longest_mm=float(maps[tuple(joint["hot_slots"])]),
                patterns=[dict(hot_slots=k, min_longest_mm=float(v)) for k, v in sorted(maps.items())])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    primary = json.loads(args.evidence.read_bytes())
    result = {}
    for rows, cols, topology in ((4, 6, "mesh"), (8, 8, "folded_torus")):
        p, start = problem(rows, cols, topology, args.upstream.resolve(), False, True)
        name = p.name + "_grid_start"
        result[name] = audit(p, start, primary["cases"][name]["joint"])
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n",encoding="utf8",newline="\n")


if __name__ == "__main__":
    main()
