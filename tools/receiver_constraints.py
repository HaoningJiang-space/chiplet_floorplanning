"""Deduct receiver setup/hold from the replayed three-layout Xyce windows (plan: docs/receiver-constraint-plan.md).

Inputs are the historical chain's outputs (replayed at d180f66): the three-layout
comparison JSON, its manifest's cold/hot Xyce runs (deck.cir + deck.cir.csv per
time step) and the hash-locked SKY130 dfxtp_1 Liberty tables at tt 1.8 V, 25 and
100 C. For each receiver and edge the D and CLK 20-80% slews are measured from the
same waves the windows came from, the receiver's temperature is read from its deck
instance, and the Liberty constraint is interpolated bilinearly in slews and
linearly in temperature (no extrapolation). Slack = window - constraint, U = 0.
The layout-pair screen is the frozen rule of the original comparison.
"""
import argparse
from hashlib import sha256
from itertools import combinations
import json
import math
from pathlib import Path
import re

import numpy as np

VDD = 1.8
STEPS = (5., 2.5)
EDGES = (('rise', 21.), ('fall', 41.))  # launch times (ns) used by the original measurement


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def crossing_ns(t, v, level, rising):
    above = v >= level if rising else v <= level
    hit = np.flatnonzero(above[1:] & ~above[:-1])
    if not hit.size:
        raise ValueError('no crossing')
    i = hit[0]
    return float(t[i] + (level - v[i])*(t[i + 1] - t[i])/(v[i + 1] - v[i]))


def edge_metrics(t, v, start, rising):
    """50% time and 20-80% slew of the first transition in [start-0.05, start+5] ns (original window)."""
    mask = (t >= start - .05) & (t <= start + 5)
    t, v = t[mask], v[mask]
    low, high = crossing_ns(t, v, .2*VDD, rising), crossing_ns(t, v, .8*VDD, rising)
    return crossing_ns(t, v, .5*VDD, rising), abs(high - low)


def receivers(deck):
    """{lane: (clk node, D node, temperature C)} from X_rx_* dfxtp_1 instances."""
    default = float(re.search(r'(?m)^\.options device temp=([0-9.eE+-]+)', deck).group(1))
    out = {}
    for line in deck.splitlines():
        if line.startswith('X_rx_') and 'sky130_fd_sc_hd__dfxtp_1' in line:
            name, clk, d = line.split()[:3]
            temp = re.search(r'cell_temp_c=([0-9.eE+-]+)', line)
            out[name[len('X_rx_'):]] = (clk, d, float(temp.group(1)) if temp else default)
    if len(out) != 8:
        raise ValueError('expected eight receivers')
    return out


def measure_run(folder):
    """Per (step, lane, edge, window): slews (ns) and receiver temperature (C)."""
    rows = {}
    for step in STEPS:
        sub = Path(folder)/f'step_{step:g}ps'
        rx = receivers((sub/'deck.cir').read_text())
        header = (sub/'deck.cir.csv').open().readline().strip().split(',')
        nodes = sorted({n for clk, d, _ in rx.values() for n in (clk, d)})
        wave = np.loadtxt(sub/'deck.cir.csv', delimiter=',', skiprows=1,
                          usecols=[0] + [header.index(f'V({n.upper()})') for n in nodes])
        t, v = wave[:, 0]*1e9, dict(zip(nodes, wave[:, 1:].T))
        for lane, (clk, d, temp) in rx.items():
            cv, dv = v[clk], v[d]
            for edge, launch in EDGES:
                _, d_slew = edge_metrics(t, dv, launch, edge == 'rise')
                _, capture_slew = edge_metrics(t, cv, launch + 10, True)
                _, previous_slew = edge_metrics(t, cv, launch - 10, True)
                rows[step, lane, edge, 'setup'] = dict(d_slew_ns=d_slew, clk_slew_ns=capture_slew, temp_c=temp)
                rows[step, lane, edge, 'hold'] = dict(d_slew_ns=d_slew, clk_slew_ns=previous_slew, temp_c=temp)
    return rows


class Constraint:
    """Liberty setup_rising/hold_rising of dfxtp_1; index_1 = CLK slew, index_2 = D slew (ns)."""
    def __init__(self, cold_lib, hot_lib):
        self.tables, self.temps = [], (25., 100.)
        for path in (cold_lib, hot_lib):
            arcs = json.loads(Path(path).read_text())['pin,D']['timing']
            self.tables.append({(arc['timing_type'], kind): arc[f'{kind}_constraint,vio_3_3_1']
                                for arc in arcs for kind in ('rise', 'fall')})

    @staticmethod
    def _bilinear(table, x, y):
        xs, ys, z = (np.asarray(table[k], float) for k in ('index_1', 'index_2', 'values'))
        if not (xs[0] <= x <= xs[-1] and ys[0] <= y <= ys[-1]):
            raise ValueError(f'slew outside Liberty table: clk {x}, d {y}')
        i = min(np.searchsorted(xs, x, 'right') - 1, len(xs) - 2)
        j = min(np.searchsorted(ys, y, 'right') - 1, len(ys) - 2)
        u, w = (x - xs[i])/(xs[i + 1] - xs[i]), (y - ys[j])/(ys[j + 1] - ys[j])
        return float((1-u)*(1-w)*z[i, j] + u*(1-w)*z[i + 1, j] + (1-u)*w*z[i, j + 1] + u*w*z[i + 1, j + 1])

    def __call__(self, window, edge, clk_slew, d_slew, temp):
        if not self.temps[0] <= temp <= self.temps[1]:
            raise ValueError(f'temperature outside Liberty pair: {temp}')
        key = (window + '_rising', edge)
        a, b = (self._bilinear(t[key], clk_slew, d_slew) for t in self.tables)
        return a + (b - a)*(temp - self.temps[0])/(self.temps[1] - self.temps[0])


def classify(cold, hot, controls_passed, discrepancy):
    """The original comparison's frozen empirical screen (compare_xyce_hot_layouts.classify at d180f66)."""
    def resolved_sign(values, terms=2):
        screen = max(abs(values[1] - values[0]), terms*discrepancy)
        return 1 if min(values) > screen else -1 if max(values) < -screen else 0
    c, h = resolved_sign(cold), resolved_sign(hot)
    interaction = [b - a for a, b in zip(cold, hot)]
    return dict(cold_pair_difference_ps=cold, hot_pair_difference_ps=hot, interaction_ps=interaction,
                ordering='unresolved' if not controls_passed or not c or not h else 'stable' if c == h else 'changed',
                interaction_status='unresolved' if not controls_passed else
                'observed_interaction' if resolved_sign(interaction, 4) else 'no_resolved_interaction')


def pair(a, b, quantity, passed, discrepancy):
    keys = sorted({k[1:] for k in a})
    paths = [dict(lane=lane, edge=edge, window=kind, **classify(
        *[[(b[s, lane, edge, kind][f'{mode}_{quantity}_ns'] - a[s, lane, edge, kind][f'{mode}_{quantity}_ns'])*1000
           for s in STEPS] for mode in ('cold', 'hot')], passed, discrepancy)) for lane, edge, kind in keys]
    minima = []
    for kind in ('setup', 'hold'):
        paired = [[(min(r[f'{mode}_{quantity}_ns'] for k, r in b.items() if k[0] == s and k[3] == kind)
                    - min(r[f'{mode}_{quantity}_ns'] for k, r in a.items() if k[0] == s and k[3] == kind))*1000
                   for s in STEPS] for mode in ('cold', 'hot')]
        minima.append(dict(window=kind, **classify(*paired, passed, discrepancy)))
    return dict(paths=paths, minimum=minima)


def counts(result):
    return {k: sum(r['ordering'] == k for r in result['paths']) for k in ('stable', 'changed', 'unresolved')} | \
        dict(resolved_interactions=sum(r['interaction_status'] == 'observed_interaction' for r in result['paths']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('comparison', type=Path, help='replayed xyce-three-layout-comparison.json')
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--liberty-25', type=Path, required=True)
    parser.add_argument('--liberty-100', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    comparison, manifest = json.loads(args.comparison.read_text()), json.loads(args.manifest.read_text())
    passed = all(c['numerical_control_passed'] for c in comparison['uniform_controls'])
    discrepancy = max(c['max_abs_difference_ps'] for c in comparison['uniform_controls'])
    constraint = Constraint(args.liberty_25, args.liberty_100)
    layouts = {}
    for name, runs in manifest['layouts'].items():
        measured = {mode: measure_run(runs[mode]) for mode in ('cold', 'hot')}
        rows = {}
        for r in comparison['summaries'][name]['paths']:
            key = (r['step_ps'], r['lane'], r['edge'], r['window'])
            row = dict(r)
            for mode in ('cold', 'hot'):
                m = measured[mode][key]
                c = constraint(r['window'], r['edge'], m['clk_slew_ns'], m['d_slew_ns'], m['temp_c'])
                row.update({f'{mode}_{k}': v for k, v in m.items()})
                row[f'{mode}_constraint_ns'] = c
                row[f'{mode}_slack_ns'] = r[f'{mode}_window_ns'] - c
            row['constraint_thermal_change_ps'] = (row['hot_constraint_ns'] - row['cold_constraint_ns'])*1000
            rows[key] = row
        layouts[name] = rows
    pairs = {}
    for a, b in combinations(('rot180', 'rot90', 'rot270'), 2):
        window, slack = (pair(layouts[a], layouts[b], q, passed, discrepancy) for q in ('window', 'slack'))
        pairs[f'{a}__{b}'] = dict(window_counts=counts(window), slack_counts=counts(slack),
                                  minimum_window=window['minimum'], minimum_slack=slack['minimum'],
                                  slack_paths=slack['paths'])
    every = [r for rows in layouts.values() for r in rows.values()]
    result = dict(
        physical_qualified=False, plan='docs/receiver-constraint-plan.md', source_sha256=digest(__file__),
        comparison_sha256=digest(args.comparison), manifest_sha256=digest(args.manifest),
        liberty_sha256={str(p): digest(p) for p in (args.liberty_25, args.liberty_100)},
        uniform_controls_passed=passed, uniform_discrepancy_ps=discrepancy, clock_uncertainty_ns=0.0,
        ranges=dict({f'{mode}_{k}': [min(r[f'{mode}_{k}'] for r in every), max(r[f'{mode}_{k}'] for r in every)]
                     for mode in ('cold', 'hot') for k in ('d_slew_ns', 'clk_slew_ns', 'temp_c', 'constraint_ns', 'slack_ns')},
                    constraint_thermal_change_ps=[min(r['constraint_thermal_change_ps'] for r in every),
                                                  max(r['constraint_thermal_change_ps'] for r in every)]),
        pairs=pairs,
        paths={name: [dict(step_ps=k[0], lane=k[1], edge=k[2], **{x: y for x, y in r.items()
                                                                   if x not in ('step_ps', 'lane', 'edge')})
                      for k, r in sorted(rows.items())] for name, rows in layouts.items()})
    if not all(math.isfinite(v) for rng in result['ranges'].values() for v in rng):
        raise ValueError('non-finite result')
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(ranges=result['ranges'], counts={k: dict(window=v['window_counts'], slack=v['slack_counts'])
                                                         for k, v in pairs.items()}), indent=1))


if __name__ == '__main__':
    main()
