"""Compare the actual relation_space entry and joint moves at both start-layout wire caps."""

import argparse
import json
from pathlib import Path
import platform
import subprocess
from time import perf_counter

import numpy as np
import scipy
from scipy.optimize import linear_sum_assignment

from chiplet_floorplanning.placement.evaluate import Evaluator
from chiplet_floorplanning.placement.geometry import is_legal, pin_manhattan_um
from chiplet_floorplanning.placement.linked_slots import linked_patterns
from chiplet_floorplanning.placement.lp import MILP_STATUS
from chiplet_floorplanning.placement.methods import Run, relation_space
from chiplet_floorplanning.placement.problem import Layout
from chiplet_floorplanning.placement.thermal import AMBIENT_C, solve, thermal_case_data
from check_power_crossings import hot_to_cold
from continuous_row_exchanges import row_exchanges
from scale_slot_margin import REV, SEED, SlotPackage, problem


def wire_metrics(p, layout):
    wire = pin_manhattan_um(p, layout)
    return float(wire.sum()/1e6), float(wire.max(initial=0)/1000)


def admissible(total, longest, caps):
    return total <= caps[0] + 1e-9 and longest <= caps[1] + 1e-9


def point(p, start, layout, peak):
    total, longest = wire_metrics(p, layout)
    return dict(peak_c=float(peak), total_m=total, longest_mm=longest,
                moved=int(np.any(layout.centre_um != start.centre_um, axis=1).sum()),
                centre_um=layout.centre_um.tolist(), rotation_deg=layout.rotation_deg.tolist())


class ProjectedRun(Run):
    """Run the relation seeds and LP proposals, admitting only dual-cap slot assignments."""
    def __init__(self, evaluator, start, caps):
        super().__init__(evaluator, 3, max_rounds=1)
        self.start = start
        self.caps = caps
        self.projected = {}
        self.proposals = 0

    def evaluate(self, candidates):
        eligible = []
        for layout in candidates:
            self.proposals += 1
            cost = np.abs(layout.centre_um[:, None] - self.start.centre_um[None, :]).sum(axis=2)
            _, slots = linear_sum_assignment(cost)
            key = tuple(slots.tolist())
            if key not in self.projected:
                fixed = Layout(self.start.centre_um[slots], self.start.rotation_deg)
                total, longest = wire_metrics(self.evaluator.problem, fixed)
                ok = admissible(total, longest, self.caps)
                self.projected[key] = dict(total_m=total, longest_mm=longest, eligible=ok)
                if ok:
                    eligible.append(fixed)
        return super().evaluate(eligible)


def summary(p, start, candidates, caps):
    legal = [(layout, row) for layout, row in candidates if admissible(row['total_m'], row['longest_mm'], caps)]
    best, row = min(legal, key=lambda item: (item[1]['peak_c'], item[1]['total_m']))
    initial = candidates[0][1]['peak_c']
    reverse = min((r for _, r in legal if r['peak_c'] <= initial + 1e-7),
                  key=lambda r: (r['total_m'], r['peak_c']))
    assert is_legal(p, best, 100)
    raw = solve(thermal_case_data(p, best, 100, 64), node_limit=450000)[0]
    np.testing.assert_allclose(row['peak_c'], raw['peak_power_layer_c'], rtol=0, atol=1e-6)
    return dict(best=row, reverse=reverse, gain_k=initial-row['peak_c'],
                balance_error_w=raw['energy_balance_error_w'], audit_peak_c=raw['peak_power_layer_c'],
                candidates=[r for _, r in candidates])


def baseline(p, start, caps, projected):
    begin = perf_counter()
    evaluator = Evaluator(p, 100, resolution=64, workers=1)
    run = ProjectedRun(evaluator, start, caps) if projected else Run(evaluator, 3, max_rounds=1)
    options = dict(milp_s=2., anneal_steps=8, chains=2, batch=6, levels=3)
    if projected:
        options['lp_share'] = 1.0
    relation_space(run, [start], np.random.default_rng(SEED), **options)
    assert 1 <= evaluator.solves <= 3 and np.array_equal(run.layouts[0].centre_um, start.centre_um)
    rows = [(layout, point(p, start, layout, peak)) for layout, peak in zip(run.layouts, run.peaks)]
    result = summary(p, start, rows, caps)
    result.update(extra_fv_charged=evaluator.solves-1, milp_status=MILP_STATUS['status'],
                  distinct_other_layouts=len(rows)-1, distinct_new_thermal_states=len(evaluator.cache)-1,
                  rounds=run.rounds, stop=run.stop_reason)
    if projected:
        result.update(raw_proposals=run.proposals, unique_projected=len(run.projected),
                      eligible_projected=sum(r['eligible'] for r in run.projected.values()),
                      projected_metrics=list(run.projected.values()))
    result['elapsed_s'] = perf_counter()-begin
    return result


def joint(p, start, caps):
    begin = perf_counter()
    candidates, stats = linked_patterns(p, start, *caps, max_moved=6)
    assert stats['complete']
    # The paired protocol also charges the initial reference and final rebuild.
    package = SlotPackage(p, start)
    initial = package.temperatures(p.power_w)
    old_peak = AMBIENT_C + initial[package.active].max()
    # If geometry alone proves that power cannot move, no adjoint is needed.
    original = next(v for v in candidates if np.array_equal(v.power_w, p.power_w))
    same = Layout(start.centre_um[original.chip_to_slot], start.rotation_deg)
    checked = [(start, point(p, start, start, old_peak))]
    if not np.array_equal(start.centre_um, same.centre_um):
        checked.append((same, point(p, start, same, old_peak)))
    unchecked = [v for v in candidates if v is not original]
    if unchecked:
        for cells in package.slots:
            package.observe(cells[initial[cells].argmax()])
        package.observe(package.active[initial[package.active].argmax()])
    n_checks = 0
    for _ in range(2):
        if not unchecked:
            break
        response = np.stack(list(package.rows.values()))
        i = min(range(len(unchecked)), key=lambda j: (np.max(response @ unchecked[j].power_w),
                                                       unchecked[j].wire_m))
        v = unchecked.pop(i)
        physical = Layout(start.centre_um[v.chip_to_slot], start.rotation_deg)
        assert is_legal(p, physical, 100) and admissible(*wire_metrics(p, physical), caps)
        field = package.temperatures(v.power_w)
        cell = package.active[field[package.active].argmax()]
        checked.append((physical, point(p, start, physical, AMBIENT_C + field[cell])))
        package.observe(cell)
        n_checks += 1
    result = summary(p, start, checked, caps)
    result.update(extra_fv_charged=n_checks, observer_rows=len(package.rows), geometry=stats,
                  elapsed_s=perf_counter()-begin)
    return result


def continuous(p, start, caps):
    begin = perf_counter()
    choices, families = row_exchanges(p, start, caps)
    evaluator = Evaluator(p, 100, resolution=64, workers=1)
    layouts = [start] + [v for _, v in choices[:2]]
    rows = [(layout, point(p, start, layout, peak)) for layout, peak in
            zip(layouts, evaluator.peaks_c(layouts))]
    assert evaluator.solves <= 3 and all(admissible(row['total_m'], row['longest_mm'], caps) for _, row in rows)
    result = summary(p, start, rows, caps)
    result.update(extra_fv_charged=evaluator.solves-1, families=families,
                  feasible_families=len(choices), elapsed_s=perf_counter()-begin)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    up = args.upstream.resolve()
    assert subprocess.check_output(['git', '-C', str(up), 'rev-parse', 'HEAD'], text=True).strip() == REV
    record = dict(seed=SEED, rapidchiplet=REV, python=platform.python_version(),
                  numpy=np.__version__, scipy=scipy.__version__, extra_fv_cap=2,
                  common_start_fv=1, independent_final_fv=1, cases={})
    for rows, cols, network in ((4, 6, 'mesh'), (8, 8, 'folded_torus')):
        before = perf_counter()
        p, start = problem(rows, cols, network, up, False, True)
        caps = wire_metrics(p, start)
        input_s = perf_counter()-before
        report = dict(cap_m=caps[0], cap_longest_mm=caps[1], shared_input_s=input_s)
        for name, method in [('relation_space_slots', lambda: baseline(p, start, caps, True)),
                             ('joint_up_to_six', lambda: joint(p, start, caps)),
                             ('relation_space_native', lambda: baseline(p, start, caps, False)),
                             ('continuous_row_exchange', lambda: continuous(p, start, caps))]:
            result = method()
            result['total_s'] = result['elapsed_s'] + input_s
            report[name] = result
            print(p.name, name, result['best']['peak_c'], result['total_s'], flush=True)
        before = perf_counter()
        feasible = []
        maps, domain = linked_patterns(p, start, *caps, node_limit=5000, on_feasible=feasible.append)
        domain['elapsed_s'] = perf_counter()-before
        domain['witnesses'] = []
        for perm in feasible:
            layout = Layout(start.centre_um[perm], start.rotation_deg)
            total, longest = wire_metrics(p, layout)
            assert is_legal(p, layout, 100) and admissible(total, longest, caps)
            domain['witnesses'].append(dict(slot_of_die=perm.tolist(), total_m=total, longest_mm=longest,
                changed_power_slots=int(np.count_nonzero(p.power_w[perm] != p.power_w))))
        domain['representatives'] = [dict(slot_of_die=v.chip_to_slot.tolist(), total_m=v.wire_m,
                                          power_w=v.power_w.tolist()) for v in maps]
        report['all_permutations'] = domain
        before = perf_counter()
        crossing = hot_to_cold(p, start, caps[1])
        crossing['elapsed_s'] = perf_counter()-before
        report['independent_crossing'] = crossing
        np.testing.assert_allclose([report[name]['candidates'][0]['peak_c'] for name in
            ('relation_space_slots','relation_space_native')], report['joint_up_to_six']['candidates'][0]['peak_c'],
            atol=1e-6, rtol=0)
        record['cases'][p.name] = report
        args.output.parent.mkdir(exist_ok=True, parents=True)
        args.output.write_text(json.dumps(record, indent=2, allow_nan=False)+'\n', encoding='utf8', newline='\n')


if __name__ == '__main__':
    main()
