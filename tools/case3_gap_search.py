"""Paired single-seed placement search on the frozen Case3 throughput witness."""
import argparse
import json
from pathlib import Path

import numpy as np

from case3_phy_geometry import LIMIT_C, REACH_MM, heat_score, sizes_mm
from chiplet_floorplanning.cli import source_revision
from chiplet_floorplanning.placement import Layout, Problem, is_legal
from chiplet_floorplanning.placement.geometry import boxes
from cut_traffic import EVIDENCE, channels, digest
from module_capacity import EDGES, SIGNALS, bank_table, thermal_job, workload
from wire_heat_bound import thermal_modes

SEED = 20261119
STEPS_UM = (-1000, -500, -250, -125, 125, 250, 500, 1000)


def evidence(name):
    return json.loads((EVIDENCE / name).read_bytes())


class Case3:
    def __init__(self, case_path):
        self.case_hash = digest(case_path)
        checks = evidence('case3-joint-clearance-v1.json')['source_case_checks']['cases']
        if self.case_hash != next(r['case_sha256'] for r in checks if r['case'] == 'Case3'):
            raise ValueError('input differs from the frozen Case3')
        self.problem = Problem.from_imported(json.loads(case_path.read_bytes()))
        self.row = next(r for r in evidence('case3-selective-rate-v1.json')['threshold_witnesses']
                        if r['id'] == 'two-fast-local')
        layout = next(r for r in evidence('capacity-cost-v1.json')['physical_layouts']
                      if r['layout'] == self.row['id'])
        ref = next(r for r in layout['reference'] if r['shares'] == [24, 12, 4] and r['target_TB_s'] == .65)
        self.config = ref['sized']
        self.modules = np.array(self.config['modules'])
        self.cap_m = ref['uniform']['total_wire_m']
        self.demand, _ = workload((24, 12, 4), .65)
        self.start = Layout(np.array(self.row['centres_um']), np.array(self.row['actual_config']['rotation_deg']))
        cert = next(r['certificate'] for r in evidence('global-heat-floor-v1.json')['cases']
                    if r['certificate']['case'] == 'Case3')
        self.radii, self.weights = thermal_modes(cert)
        self.self_k = np.array([die['self_floor_k'] for die in cert['dies']])
        self.size_mm = sizes_mm(self.problem, self.row['parity'])

    def geometry(self, xy):
        # Rigid CPU/DRAM pairs retain their memory pin lengths. bank_table also checks that invariant.
        memory, cost, reach = bank_table(self.problem, dict(self.row, centres_um=xy.tolist()))
        selected = (np.arange(len(EDGES)), self.modules)
        return dict(wire_m=float(memory + cost[selected].sum()), max_cpu_mm=float(reach[selected].max()))

    def field(self, xy, grid):
        row = dict(self.row, centres_um=xy)
        return thermal_job((self.problem, row, self.modules, self.config['endpoint_w'], grid))[2]

    def cuts(self, parent):
        memory = self.problem.pin_chip[(self.problem.pin_chip >= 4).any(axis=1)]
        cuts = []
        for axis, right, gap in channels(self.problem, parent):
            cpu = right[:4]
            crosses = cpu[EDGES[:, 0]] != cpu[EDGES[:, 1]]
            capacity = sum(np.asarray(self.config['capacity_each_direction_gbps'])[crosses])
            demand = self.demand[np.ix_(cpu, ~cpu)].sum()
            assert demand <= capacity + 1e-8
            signals = SIGNALS * self.modules[crosses].sum() + np.count_nonzero(right[memory[:, 0]] != right[memory[:, 1]])
            cuts.append(dict(axis=int(axis), high=np.flatnonzero(right).tolist(), gap_um=gap, signals=int(signals),
                             demand_gbps=float(demand), capacity_gbps=float(capacity)))
        return cuts


def gap_score(bounds, cuts):
    score = 0.
    for cut in cuts:
        axis = cut['axis']
        right = np.zeros(len(bounds), dtype=bool)
        right[cut['high']] = True
        gap = max(0., bounds[right, axis].min() - bounds[~right, axis + 2].max())
        fraction = cut['demand_gbps'] / cut['capacity_gbps'] if cut['capacity_gbps'] else 0.
        score += (gap - cut['gap_um']) * cut['signals'] * (1 + fraction) / 1e6
    return float(score)


def candidates(case, parent, cuts, evaluated):
    groups = [(axis, (i, i + 4)) for axis in (0, 1) for i in range(4)]
    for cut in cuts:
        high = tuple(cut['high'])
        low = tuple(i for i in range(8) if i not in high)
        groups.extend([(cut['axis'], low), (cut['axis'], high)])
    seen = set(evaluated)
    pool = []
    for axis, group in groups:
        for step in STEPS_UM:
            xy = parent.centre_um.copy()
            xy[list(group), axis] += step
            key = xy.tobytes()
            trial = Layout(xy, parent.rotation_deg)
            if key in seen or not is_legal(case.problem, trial, 0):
                continue
            seen.add(key)
            exact = case.geometry(xy)
            if exact['wire_m'] > case.cap_m + 1e-10 or exact['max_cpu_mm'] > REACH_MM + 1e-10:
                continue
            proxy = heat_score(xy / 1000, case.size_mm, case.problem.power_w, case.radii, case.weights, case.self_k)
            pool.append(dict(**exact, centres_um=xy.tolist(), axis=axis, group=list(group), step_um=step,
                             coupling_proxy_k=proxy, gap_score_m=gap_score(boxes(case.problem, trial), cuts)))
    return pool


def search(case, guided):
    rng = np.random.default_rng(SEED)
    initial = case.start.centre_um
    start = dict(centres_um=initial.tolist(), **case.geometry(initial), **case.field(initial.tolist(), 64))
    assert abs(start['peak_c'] - case.config['peak_c_by_grid']['64']) < 1e-6
    assert abs(start['wire_m'] - case.config['total_wire_m']) < 1e-8
    rows, rounds, evaluated = [start], [], {initial.tobytes()}
    for _ in range(3):
        parent_index = min(range(len(rows)), key=lambda i: (rows[i]['peak_c'], rows[i]['wire_m']))
        parent = Layout(np.asarray(rows[parent_index]['centres_um']), case.start.rotation_deg)
        cuts = case.cuts(parent)
        pool = candidates(case, parent, cuts, evaluated)
        # Share the thermal shortlist and seeded tie order. Only the gap/capacity priority changes.
        pool.sort(key=lambda r: r['coupling_proxy_k'])
        short = pool[:(len(pool) + 1)//2]
        ordered = [short[i] for i in rng.permutation(len(short))]
        if guided:
            ordered.sort(key=lambda r: r['gap_score_m'])
        selected = ordered[:4]
        rounds.append(dict(parent=parent_index, cuts=cuts, feasible=len(pool), shortlist=len(short),
                           first_row=len(rows), selected=len(selected)))
        for row in selected:
            row.update(case.field(row['centres_um'], 64))
            evaluated.add(np.asarray(row['centres_um']).tobytes())
            rows.append(row)
        if not selected:
            break
    best = min(range(len(rows)), key=lambda i: (rows[i]['peak_c'], rows[i]['wire_m']))
    shortest = min((i for i in range(len(rows)) if rows[i]['peak_c'] <= LIMIT_C),
                   key=lambda i: (rows[i]['wire_m'], rows[i]['peak_c']), default=None)
    return dict(fv_solves=len(rows), best=best, shortest_within_109c=shortest, rounds=rounds, rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    case = Case3(args.case)
    runs = {name: search(case, guided) for name, guided in [('baseline', False), ('guided', True)]}
    checks = {}
    for name, row in [('start', runs['baseline']['rows'][0]),
                      *((name, run['rows'][run['best']]) for name, run in runs.items())]:
        checks[name] = {grid: case.field(row['centres_um'], grid) for grid in (96, 160)}
    output = dict(protocol_commit='84fd344', code=source_revision(), case_sha256=case.case_hash,
                  initial_layout=case.row['id'], seed=SEED, search_grid=64, budget_per_arm=13,
                  wire_cap_m=case.cap_m, reach_mm=REACH_MM, target_tb_s=.65, shares=[.6, .3, .1],
                  modules=case.modules.tolist(), endpoint_w=case.config['endpoint_w'],
                  package_power_w=float(case.problem.power_w.sum() + 2*sum(case.config['endpoint_w'])),
                  runs=runs, finalist_checks=checks)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(output, f, indent=2, allow_nan=False)
        f.write('\n')


if __name__ == '__main__':
    main()
