"""Spend thermally invariant pin-length savings in a matched-budget local search."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem, is_legal, solve, thermal_case_data
from chiplet_floorplanning.placement.thermal import die_peaks_c
from fixed_field_wire import actions, move, refine
from headroom_selection import conditions, coupling_rise, length_m, move_layout


def encoded(layout):
    return layout.centre_um.astype('<f8').tobytes() + layout.rotation_deg.astype('<i2').tobytes()


def footprint(layout, problem, powers):
    size = np.where((layout.rotation_deg % 180 != 0)[:, None], problem.size_um[:, ::-1], problem.size_um)
    return sorted(map(tuple, np.column_stack((layout.centre_um, size, powers))))


class Neighborhood:
    def __init__(self, problem, parent, gap_um, trace):
        self.problem = problem
        self.gap_um = gap_um
        self.trace = [e['action'] for e in trace]
        self.scenarios = conditions(problem)
        self.powers = np.column_stack([p.power_w for p in self.scenarios.values()])
        self.layouts = []
        self.states = []
        self.identities = {}
        self.pools = {}
        self.evaluations = {}
        self.cost = {}
        self.register(parent, None, ('parent',))

    def rewire(self, layout):
        for action in self.trace:
            layout = move(layout, action)
        return layout

    def register(self, layout, source, action):
        key = encoded(layout)
        if key in self.identities:
            return self.identities[key]
        idx = len(self.layouts)
        raw = length_m(self.problem, layout)
        alternative = raw
        if self.trace:
            other = self.rewire(layout)
            assert is_legal(self.problem, other, self.gap_um)
            assert footprint(other, self.problem, self.powers) == footprint(layout, self.problem, self.powers)
            alternative = length_m(self.problem, other)
        self.identities[key] = idx
        self.layouts.append(layout)
        self.states.append(dict(source=source, action=action, raw_m=raw, rewired_m=alternative,
                                best_m=min(raw, alternative)))
        return idx

    def proposals(self, idx):
        if idx in self.pools:
            return self.pools[idx]
        parent = self.layouts[idx]
        p = self.problem
        size = np.where((parent.rotation_deg % 180 != 0)[:, None], p.size_um[:, ::-1], p.size_um)
        singles = [('single', i, axis, shift) for i in range(p.count) for axis in (0, 1)
                   for shift in (-4000, -2000, -500, 500, 2000, 4000)]
        swaps = [('swap', i, j) for i, j in combinations(range(p.count), 2)
                 if p.power_w[i] != p.power_w[j] and np.array_equal(size[i], size[j])]
        seed = int.from_bytes(sha256(encoded(parent)).digest()[:8], 'little')
        rng = np.random.default_rng(seed)
        result = []
        for options, limit in ((singles, 20), (swaps, 8)):
            legal = []
            for action in options:
                trial = move_layout(parent, action)
                if is_legal(p, trial, self.gap_um):
                    legal.append((action, trial))
            indices = sorted(rng.choice(len(legal), limit, replace=False)) if len(legal) > limit else range(len(legal))
            for i in indices:
                action, trial = legal[i]
                result.append(self.register(trial, idx, action))
        assert len(set(result)) == len(result)
        self.pools[idx] = result
        return result

    def evaluate(self, idx, scenario):
        key = idx, scenario
        if key not in self.evaluations:
            p = self.scenarios[scenario]
            layout = self.layouts[idx]
            start = perf_counter()
            state, field, edges = solve(thermal_case_data(p, layout, self.gap_um, 64))
            peaks = die_peaks_c(p, layout, field, edges)
            assert abs(max(peaks) - state['peak_power_layer_c']) < 1e-7
            self.evaluations[key] = peaks
            self.cost[key] = (perf_counter()-start, abs(state['energy_balance_error_w']))
        return self.evaluations[key]

    def search(self, scenario, cap_m, length_key):
        p = self.scenarios[scenario]
        sequence = [0]
        rounds = []
        for _ in range(3):
            current = min(sequence, key=lambda i: round(float(self.evaluate(i, scenario).max()), 9))
            eligible = [i for i in self.proposals(current)
                        if self.states[i][length_key] <= cap_m + 1e-9 and i not in sequence]
            base = self.evaluate(current, scenario)
            reference = coupling_rise(p, self.layouts[current])
            def priority(i):
                estimated = base + (coupling_rise(p, self.layouts[i])-reference)
                return round(float(estimated.max()), 9)
            chosen = sorted(eligible, key=priority)[:4]
            for i in chosen:
                self.evaluate(i, scenario)
            rounds.append(dict(parent=current, eligible=len(eligible), queries=chosen))
            sequence.extend(chosen)
            if not chosen:
                break
        return dict(sequence=sequence, rounds=rounds)

    def selection(self, ids, scenario, length_key):
        peaks = {i: float(self.evaluate(i, scenario).max()) for i in ids}
        peak_cap = float(self.evaluate(0, scenario).max())
        coolest = min(ids, key=lambda i: round(peaks[i], 9))
        shortest = min((i for i in ids if peaks[i] <= peak_cap+1e-9),
                       key=lambda i: round(self.states[i][length_key], 9))
        def point(i):
            return dict(id=i, peak_c=peaks[i], length_m=self.states[i][length_key])
        return dict(coolest=point(coolest), shortest=point(shortest))


def run_parent(job):
    p, gap_um, parent, record, group, archive_id = job
    start = perf_counter()
    rotations, swaps, _ = actions(p)
    _, trace = refine(p, parent, rotations+swaps)
    elapsed = perf_counter()-start
    previous = record['states']['joint']['trace']
    assert [tuple(e['action']) for e in trace] == [tuple(e['action']) for e in previous]
    assert all(abs(a['length_m']-b['length_m']) < 1e-9 for a,b in zip(trace, previous))
    box = Neighborhood(p, parent, gap_um, trace)
    first = [0, *box.proposals(0)]
    baseline = box.states[0]['raw_m']
    assert abs(box.states[0]['best_m']-record['states']['joint']['length_m']) < 1e-9
    comparisons = []
    for scenario in box.scenarios:
        assert abs(float(box.evaluate(0, scenario).max())-record['parent_fields'][scenario]['peak_c']) < 1e-6
        for label, cap in [('parent', baseline), ('archive', group['cap_m'])]:
            cases = {k: box.search(scenario, cap, k) for k in ('raw_m', 'best_m')}
            common = min(len(arm['sequence']) for arm in cases.values())
            for k, arm in cases.items():
                assert all(box.states[i][k] <= cap+1e-9 for i in arm['sequence'])
                arm['matched'] = box.selection(arm['sequence'][:common], scenario, k)
                arm['full'] = box.selection(arm['sequence'], scenario, k)
            comparisons.append(dict(scenario=scenario, budget=label, cap_m=cap, common_queries=common, arms=cases))
    charged_union = len(box.evaluations)
    # Only after both searches finish, measure the first proposal set for the mechanism check.
    for row in comparisons:
        cap, scenario = row['cap_m'], row['scenario']
        base_ids = [i for i in first if box.states[i]['raw_m'] <= cap+1e-9]
        new_ids = [i for i in first if box.states[i]['best_m'] <= cap+1e-9 and i not in base_ids]
        for i in first:
            box.evaluate(i, scenario)
        row['first'] = dict(base_count=len(base_ids), new_ids=new_ids,
                            raw=box.selection(base_ids, scenario, 'raw_m'),
                            best=box.selection([*base_ids,*new_ids], scenario, 'best_m'))
    return dict(archive_id=archive_id, archive_budget=group['budget'], parent_kinds=group['parent_kinds'],
                trace=trace, prepass_s=elapsed, first_ids=first, states=box.states, comparisons=comparisons,
                temperatures={s:{i:float(v.max()) for (i,sc),v in box.evaluations.items() if sc==s}
                              for s in box.scenarios}, search_unique_solves64=charged_union,
                extra_first_solves64=len(box.evaluations)-charged_union,
                max_balance_error_w=max(e for t,e in box.cost.values()))


def reconstruct(parent, states, idx):
    steps = []
    while idx:
        state = states[idx]
        steps.append(state['action'])
        idx = state['source']
    for action in reversed(steps):
        parent = move_layout(parent, action)
    return parent


def fine_checks(p, gap_um, parents, rows):
    controls = []
    scenarios = conditions(p)
    for budget in ('parent', 'archive'):
        candidates = []
        for data in rows:
            for c in data['comparisons']:
                if c['budget'] == budget:
                    raw, best = [c['arms'][k]['matched']['coolest'] for k in ('raw_m','best_m')]
                    candidates.append((raw['peak_c']-best['peak_c'], data, c, raw, best))
        for sign in (1,-1):
            gain, data, c, raw, best = max(candidates, key=lambda item: sign*item[0])
            if sign*gain <= 0.1:
                continue
            measured = []
            for point, variant in ((raw, False),(best, True)):
                state = data['states'][point['id']]
                layout = reconstruct(parents[data['archive_id']], data['states'], point['id'])
                if variant and state['rewired_m'] < state['raw_m']:
                    for e in data['trace']:
                        layout = move(layout, e['action'])
                assert is_legal(p,layout,gap_um) and abs(length_m(p,layout)-point['length_m']) < 1e-9
                summary, _, _ = solve(thermal_case_data(scenarios[c['scenario']],layout,gap_um,96))
                measured.append(dict(id=point['id'], length_m=point['length_m'], peak_c=summary['peak_power_layer_c'],
                                     energy_error_w=summary['energy_balance_error_w']))
            controls.append(dict(archive_id=data['archive_id'], budget=budget, scenario=c['scenario'],
                                 gain64_k=gain, gain96_k=measured[0]['peak_c']-measured[1]['peak_c'], points=measured))
    return controls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    evidence = Path(__file__).resolve().parents[1]/'docs/evidence'
    archives = json.loads((evidence/'headroom-selection-v1.json').read_text())['records']
    witnesses = {r['case']:r for r in json.loads((evidence/'fixed-field-wire-v1.json').read_text())['records']}
    inputs = {}
    with ProcessPoolExecutor(args.workers) as pool:
        pending = {}
        for case in archives:
            name = case['case']
            if name.startswith('Case'):
                source = args.data/'physical-calibration/atplace-import-v1'/(name+'.json')
                run = args.data/'rs-grb-v4'/name.lower()
            else:
                source = args.data/'industrial-v1/cases'/(name+'.json')
                run = args.data/'industrial-v1/runs'/name
            blob = source.read_bytes()
            assert sha256(blob).hexdigest() == case['case_sha256'] == witnesses[name]['case_sha256']
            assert sha256((run/'summary.json').read_bytes()).hexdigest() == case['summary_sha256']
            assert witnesses[name]['parent_record_sha256'] == case['raw_sha256']
            p = Problem.from_imported(json.loads(blob))
            refs = {r['archive_id']:r for r in witnesses[name]['rows']}
            parents, rows = {}, []
            inputs[name] = p, case['gap_um'], parents, rows, case
            with np.load(run/'layouts.npz') as z:
                centres, turns = z['centre_um'], z['rotation_deg']
                for g in case['groups']:
                    idx = g['archive_id']
                    assert idx not in parents
                    parent = Layout(centres[idx], turns[idx])
                    parents[idx] = parent
                    assert abs(length_m(p,parent)-refs[idx]['parent_length_m']) < 1e-9
                    future = pool.submit(run_parent, (p, case['gap_um'], parent, refs[idx], g, idx))
                    pending[future] = name
        for future in as_completed(pending):
            name = pending[future]
            p, gap, parents, rows, case = inputs[name]
            rows.append(future.result())
            if len(rows) == len(parents):
                rows.sort(key=lambda r:r['archive_id'])
                fine = fine_checks(p,gap,parents,rows)
                output = dict(case=name, case_sha256=case['case_sha256'], archive_summary_sha256=case['summary_sha256'],
                              driver_sha256=sha256(Path(__file__).read_bytes()).hexdigest(), rows=rows, fine=fine)
                (args.output/(name+'.json')).write_text(json.dumps(output, allow_nan=False)+'\n')
                print(name,'parents',len(rows),'96-grid pairs',len(fine),flush=True)


if __name__ == '__main__':
    main()
