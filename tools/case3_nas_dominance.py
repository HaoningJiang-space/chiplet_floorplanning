"""Compare archived layouts under all steady mixtures of four normalized NAS loads."""
import argparse
from itertools import permutations
import json
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Problem
from chiplet_floorplanning.placement.dominance import potential_hotspots, simplex_worst_excess
from chiplet_floorplanning.placement.thermal import AMBIENT_C
from cut_traffic import EVIDENCE, digest
from mixed_phy import bank_thermal_field
from module_capacity import bank_table, profile
from shared_capacity import NAMES, TARGET


def evidence(name):
    return json.loads((EVIDENCE / name).read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive = evidence("shared-capacity-v1.json")
    prior = evidence("case3-gap-placement-v1.json")
    assert digest(args.case) == prior["case_sha256"]
    problem = Problem.from_imported(json.loads(args.case.read_bytes()))
    rows = {r["id"]: r for r in evidence("case3-selective-rate-v1.json")["threshold_witnesses"]}
    report = dict(case_sha256=prior["case_sha256"], length_cap_m=prior["wire_cap_m"],
                  reach_mm=prior["reach_mm"], target_TB_s=TARGET, modes=NAMES, layouts=[], grids={})
    admitted = {}
    for trial in archive["physical"]["layout_trials"]:
        name = trial["layout"]
        selected = next(s for s in trial["cases"] if s["target_TB_s"] == TARGET)["sized"]
        modules = np.array(selected["modules"])
        address = np.arange(len(modules)), modules
        memory, cost, reach = bank_table(problem, rows[name])
        length, longest = float(memory + cost[address].sum()), float(reach[address].max())
        np.testing.assert_allclose([length, longest], [selected["total_wire_m"], selected["max_cpu_signal_mm"]])
        powers = []
        for mode in NAMES:
            traffic = selected["modes"][mode]
            directed = np.array(traffic["directed_raw_gbps"])
            assert directed.shape == (len(modules), 2)
            assert np.all(directed <= 256 * modules[:, None] + 1e-7) and traffic["achievable_payload_TB_s"] >= TARGET - 1e-7
            watts = (.25 * 256 * modules + .75 * directed.mean(axis=1)) / 1000
            np.testing.assert_allclose(watts, traffic["endpoint_w"])
            powers.append(watts)
        ok = length <= report["length_cap_m"] and longest <= report["reach_mm"] + 1e-9
        report["layouts"].append(dict(layout=name, length_m=length, longest_cpu_mm=longest,
                                      modules=modules.tolist(), admitted=ok))
        if ok:
            admitted[name] = (selected, np.asarray(powers), [profile(m) for m in modules])

    def field(name, grid, watts):
        return bank_thermal_field(problem, rows[name], rows[name]["actual_config"], grid,
                                  admitted[name][2], watts, node_limit=450000)

    for grid in [64, 96]:
        cells, pure = {}, {}
        for name, (selected, powers, _) in admitted.items():
            fields, peaks = [], []
            for mode, watts in zip(NAMES, powers):
                obs, rise, _ = field(name, grid, watts)
                peak = obs["peak_power_layer_c"]
                assert abs(peak - selected["modes"][mode]["peak_c_by_grid"][str(grid)]) < 1e-6
                fields.append(rise)
                peaks.append(peak)
            fields = np.asarray(fields)
            assert np.all(np.isfinite(fields) == np.isfinite(fields[0]))
            cells[name] = potential_hotspots(fields[:, np.isfinite(fields[0])].T + AMBIENT_C)
            pure[name] = peaks
        pairs = []
        for a, b in permutations(admitted, 2):
            excess, weights = simplex_worst_excess(cells[a], cells[b])
            peaks = [field(n, grid, weights @ admitted[n][1])[0]["peak_power_layer_c"] for n in (a, b)]
            np.testing.assert_allclose(peaks[0]-peaks[1], excess, atol=1e-6, rtol=0)
            pairs.append(dict(candidate=a, baseline=b, max_excess_k=excess,
                              mixture=weights.tolist(), direct_peaks_c=peaks))
        report["grids"][grid] = dict(pure_peaks_c=pure, pairs=pairs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
