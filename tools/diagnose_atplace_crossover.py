"""Post-hoc inheritance implication graphs; reads saved layouts, never solves heat."""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path

from atplace_crossover import full_key
from atplace_pin_geometry import placement_geometry
from run_atplace_search import digest, raw, write_new


def implications(a_boxes, b_boxes, gap):
    edges = []
    for i, a in enumerate(a_boxes):
        for j, b in enumerate(b_boxes):
            if i == j:
                continue
            separate = a[2]+gap <= b[0] or b[2]+gap <= a[0] or a[3]+gap <= b[1] or b[3]+gap <= a[1]
            if not separate:
                edges.append((j, i))  # A_i with B_j forbidden, so z_j => z_i.
    return sorted(edges)


def components(n, edges):
    reach = [[i == j for j in range(n)] for i in range(n)]
    for i, j in edges:
        reach[i][j] = True
    for k in range(n):
        for i in range(n):
            for j in range(n):
                reach[i][j] |= reach[i][k] and reach[k][j]
    groups, used = [], set()
    for i in range(n):
        if i not in used:
            group = [j for j in range(n) if reach[i][j] and reach[j][i]]
            groups.append(group)
            used.update(group)
    return groups


def allowed(mask, edges):
    return all(not (mask & (1 << j)) or bool(mask & (1 << i)) for j, i in edges)


def diagnose(source, evidence):
    plan = evidence['plan']
    record = evidence['records'][1]
    pareto = set(record['pareto_row_indices'])
    names = [c['name'] for c in source['chiplets']]
    gap = Decimal(plan['gap_um'])
    rows, origins = [], Counter()
    for e in record['events']:
        fresh = e['status'] in ('thermal_evaluated', 'cache_hit_new_layout')
        if fresh and e['row_index'] in pareto:
            origins[e.get('crossover', {}).get('selection', 'initial')] += 1
        c = e.get('crossover')
        if not c or c['selection'] == 'bypassed':
            continue
        a, b = [record['rows'][i]['placement'] for i in e['parent_rows']]
        _, ab = placement_geometry(source, a, gap)
        _, bb = placement_geometry(source, b, gap)
        edges = implications([ab[n] for n in names], [bb[n] for n in names], gap)
        scc = components(len(names), edges)
        masks, legal = [], {}
        for mask in range(1 << len(names)):
            p = [b[i] if mask & (1 << i) else a[i] for i in range(len(names))]
            try:
                placement_geometry(source, p, gap)
                geometric = True
            except ValueError:
                geometric = False
            if geometric != allowed(mask, edges):
                raise ValueError('Implication graph and full geometry disagree')
            if geometric:
                masks.append(mask)
                legal[full_key(p)] = p
        mixed = set(legal)-{full_key(a), full_key(b)}
        if (len(masks), len(legal), len(mixed)) != (c['legal_masks'], c['distinct_legal_states'], c['distinct_mixed_states']):
            raise ValueError('Diagnostic differs from frozen crossover receipt')
        if c['representative_mask'] not in masks:
            raise ValueError('Selected mask was not graph-legal')
        changed = [x['chiplet'] for x, y in zip(a, b) if x != y]
        full_lock = len(changed) == len(names) and not mixed
        if full_lock and len(scc) != 1:
            raise ValueError('Nontrivial no-mixed pair should be one strongly connected component')
        rows.append(dict(proposal=e['proposal'], parent_rows=e['parent_rows'],
            differing_genes=changed, edges=[dict(if_B=names[j], then_B=names[i]) for j, i in edges],
            strongly_connected_components=[[names[i] for i in g] for g in scc],
            legal_masks=masks, distinct_legal_states=len(legal), distinct_mixed_states=len(mixed),
            all_genes_differ_and_locked=full_lock, selection=c['selection'],
            post_mutation_changed_genes=[x['chiplet'] for x, y in zip(e['placement'], c['placement']) if x != y],
            event_status=e['status'], child_row=e.get('row_index'),
            new_child_in_final_pareto=bool(fresh and e['row_index'] in pareto)))
    return dict(status='verified_posthoc_geometry_diagnostic', new_thermal_solves=0,
        counts=dict(crossovers=len(rows), nontrivial_fully_locked=sum(r['all_genes_differ_and_locked'] for r in rows),
                    graph_vs_geometry_masks_checked=len(rows)*(1 << len(names)),
                    directed_cross_parent_pair_checks=len(rows)*len(names)*(len(names)-1)),
        final_pareto_origin_counts=dict(origins), rows=rows,
        interpretation='pair-conditional rigid-inheritance constraints; not permanent chip groups or causal attribution of temperature loss')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    source, evidence = json.loads(raw(a.input)), json.loads(raw(a.evidence))
    if digest(raw(a.input)) != evidence['plan']['imported_sha256']:
        raise ValueError('Source does not match the frozen experiment')
    result = diagnose(source, evidence)
    result.update(reviewed_commit='3cb5769af9a91d768276737d858fee8f55f6aef4',
                  source_evidence_sha256=digest(raw(a.evidence)), imported_sha256=digest(raw(a.input)),
                  diagnostic_source_sha256=digest(raw(__file__)))
    write_new(a.output, result)
    print(json.dumps(dict(counts=result['counts'], pareto_origins=result['final_pareto_origin_counts'],
                         new_thermal_solves=0)))


if __name__ == '__main__':
    main()
