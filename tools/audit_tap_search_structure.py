"""Exact graph audit and all-start move ablation without further thermal solves."""
import argparse
import hashlib
from itertools import product
import json
from pathlib import Path
import statistics
from build_tap_ihp_endpoints import source_bytes
from compare_tap_search import move_graph, search
from freeze_tap_geometry import verify


def component_members(graph):
    remaining = set(range(len(graph)))
    groups = []
    while remaining:
        seen = {min(remaining)}
        pending = list(seen)
        while pending:
            for neighbour in graph[pending.pop()]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    pending.append(neighbour)
        remaining -= seen
        groups.append(sorted(seen))
    return sorted(groups, key=lambda g: (-len(g), g[0]))


def full_state_graph(domain, frozen, mode):
    choices = frozen['choices']
    states, ordinals = [], []
    for ordinal, state in enumerate(product(*(range(len(c)) for c in choices))):
        try:
            verify(domain, [c[i] for c, i in zip(choices, state)])
        except ValueError:
            continue
        states.append(state)
        ordinals.append(ordinal)
    if ordinals != frozen['geometrically_legal_mixed_radix_ordinals']:
        raise ValueError('Independent legal-state enumeration disagrees')
    lookup = {s: i for i, s in enumerate(states)}
    graph = [[] for _ in states]
    for a, state in enumerate(states):
        for chip, options in enumerate(choices):
            old = options[state[chip]]
            for j, new in enumerate(options):
                moved = (old['centre_x_um'], old['centre_y_um']) != (new['centre_x_um'], new['centre_y_um'])
                rotated = old['rotation_deg'] != new['rotation_deg']
                if mode == 'atomic' and moved and rotated:
                    continue
                candidate = state[:chip] + (j,) + state[chip+1:]
                b = lookup.get(candidate)
                if b is not None and a != b:
                    graph[a].append(b)
    return states, graph


def pareto_bins(rows, temperature_step_k=1e-6, span_step_mm=1e-9):
    """Transitive objective bins, not a physical equivalence claim.

    Round to integer bins anchored at zero. Close values across a bin boundary
    need not tie. Publish members and actual values so that limitation is visible.
    """
    bins = {}
    for r in rows:
        key = (round(r['peak_c']/temperature_step_k), round(r['centre_span_mm']/span_step_mm))
        bins.setdefault(key, []).append(r)
    archive = []
    for key, members in sorted(bins.items()):
        if any(other != key and other[0] <= key[0] and other[1] <= key[1] for other in bins):
            continue
        archive.append(dict(temperature_bin=key[0], span_bin=key[1],
                            members=[dict(class_index=r['class_index'], peak_c=r['peak_c'],
                                          centre_span_mm=r['centre_span_mm']) for r in members]))
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = ['docs/evidence/tap-algorithm-oracle.json', 'docs/evidence/tap-decision-domain.json',
             'docs/evidence/tap-geometry-domains.json', 'docs/tap-search-structure-plan.md']
    raw = {p: source_bytes(p) for p in paths}
    oracle, frozen, geometry = [json.loads(raw[p]) for p in paths[:3]]
    rows = oracle['rows']
    domain = next(c['domain'] for c in geometry['cases'] if c['domain']['name'] == frozen['case'])
    if len(rows) != 77 or not all(r['thermal_admitted'] for r in rows):
        raise ValueError('Unexpected oracle')
    graphs = {mode: move_graph(rows, mode) for mode in ('atomic', 'joint')}
    optimum_class = min(range(len(rows)), key=lambda i: rows[i]['peak_c'])
    structures = {}
    for mode, graph in graphs.items():
        groups = component_members(graph)
        states, full = full_state_graph(domain, frozen, mode)
        full_groups = component_members(full)
        start_state = tuple(frozen['thermal_equivalence_classes'][0]['representative'])
        optimum_state = tuple(frozen['thermal_equivalence_classes'][optimum_class]['representative'])
        start_group = next(g for g in groups if 0 in g)
        full_start_group = next(g for g in full_groups if states.index(start_state) in g)
        structures[mode] = dict(edges=sum(map(len, graph))//2, component_members=groups,
            full_state_count=len(states), full_edges=sum(map(len, full))//2,
            full_component_sizes=list(map(len, full_groups)),
            start_can_reach_optimum_without_restarts=optimum_class in start_group,
            full_start_can_reach_optimum_without_restarts=states.index(optimum_state) in full_start_group,
            start_reachable_min_peak_c=min(rows[i]['peak_c'] for i in start_group))
    optimum = rows[optimum_class]['peak_c']
    runs, summaries = [], []
    for budget in (8, 16, 32):
        for mode, method in [('joint', 'random')] + [(m, a) for m in graphs for a in ('descent', 'annealing')]:
            batch = []
            for start in range(len(rows)):
                # Normalization fixed at old class 0 for every start and policy.
                values = [(r['peak_c']-45)/(rows[0]['peak_c']-45) for r in rows]
                record = search(lambda i: values[i], len(rows), graphs[mode], budget,
                                seed=20261112+start, method=method, start=start)
                record.update(mode=mode, method=method, budget=budget, start=start,
                              seed=20261112+start, gap_k=rows[record['best_class']]['peak_c']-optimum)
                batch.append(record)
                runs.append(record)
            summaries.append(dict(mode=mode, method=method, budget=budget,
                hits=sum(r['gap_k'] <= 1e-6 for r in batch), starts=len(batch),
                median_gap_k=statistics.median(r['gap_k'] for r in batch),
                worst_gap_k=max(r['gap_k'] for r in batch),
                mean_proposals=statistics.mean(r['proposals'] for r in batch),
                mean_cache_hits=statistics.mean(r['cache_hits'] for r in batch),
                mean_restarts=statistics.mean(r['restarts'] for r in batch)))
    result = dict(status='complete_finite_graph_and_all_start_ablation',
                  input_sha256={p: hashlib.sha256(b).hexdigest() for p, b in raw.items()},
                  structures=structures, pareto_temperature_bin_k=1e-6, pareto_span_bin_mm=1e-9,
                  pareto=pareto_bins(rows), summaries=summaries, runs=runs,
                  scope='finite-domain structural audit; restarts can cross components; no large-domain or SOTA claim')
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps(dict(structures=structures, summaries=summaries), indent=2))


if __name__ == '__main__':
    main()
