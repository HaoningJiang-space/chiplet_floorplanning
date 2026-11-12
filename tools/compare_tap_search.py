"""Equal-query baseline replay against a complete finite-domain HiTS oracle."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics


def move_graph(rows):
    keys=[[(p['centre_x_um'],p['centre_y_um'],p['rotation_deg']%180) for p in r['placement']] for r in rows]
    graph=[[] for _ in rows]
    for a in range(len(rows)):
        for b in range(a):
            if sum(x!=y for x,y in zip(keys[a],keys[b],strict=True))==1:
                graph[a].append(b);graph[b].append(a)
    return graph


def components(graph):
    remaining=set(range(len(graph)));sizes=[]
    while remaining:
        seen={min(remaining)};todo=list(seen)
        while todo:
            for n in graph[todo.pop()]:
                if n not in seen:seen.add(n);todo.append(n)
        remaining-=seen;sizes.append(len(seen))
    return sorted(sizes,reverse=True)


def score(row,reference,objective):
    thermal=(row['peak_c']-row['ambient_c'])/(reference['peak_c']-reference['ambient_c'])
    if objective=='thermal':return thermal
    if objective=='balanced':return .5*(thermal+row['centre_span_mm']/reference['centre_span_mm'])
    raise ValueError('Unknown objective')


def search(query,n,graph,budget,seed,method):
    if not 1<=budget<=n:raise ValueError('Budget outside domain')
    rng=random.Random(seed);cache={};trace=[]
    def evaluate(i):
        if i not in cache:
            cache[i]=query(i);trace.append(i)
        return cache[i]
    current=0;evaluate(current);proposals=0;stale=0;restarts=0
    while len(cache)<budget:
        proposals+=1
        unqueried=[i for i in range(n) if i not in cache]
        restart=method=='random' or not graph[current] or stale>=32
        if restart:
            candidate=rng.choice(unqueried)
            if method!='random':restarts+=1
        else:candidate=rng.choice(graph[current])
        fresh=candidate not in cache;value=evaluate(candidate)
        delta=value-cache[current]
        temperature=.1*(.01/.1)**((len(cache)-1)/max(1,budget-1))
        accepted=restart or delta<=0
        if not accepted and method=='annealing':accepted=rng.random()<math.exp(-delta/temperature)
        if accepted:current=candidate
        stale=0 if fresh else stale+1
    best=min(cache,key=lambda i:(cache[i],i))
    return dict(best_class=best,best_score=cache[best],queries=len(cache),proposals=proposals,
                restarts=restarts,queried_classes=trace)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--oracle',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();raw=args.oracle.read_bytes();oracle=json.loads(raw);rows=oracle['rows']
    if oracle['status']!='complete_finite_domain_oracle' or len(rows)!=oracle['classes'] or not all(r['thermal_admitted'] for r in rows):
        raise ValueError('Incomplete/unadmitted oracle')
    if [r['class_index'] for r in rows]!=list(range(len(rows))):raise ValueError('Oracle index mismatch')
    graph=move_graph(rows);runs=[];summaries=[]
    for objective in ('thermal','balanced'):
        values=[score(r,rows[0],objective) for r in rows];optimum=min(values)
        for budget in (8,16,32):
            for method in ('random','descent','annealing'):
                batch=[]
                for seed in range(20):
                    # The policy sees objective values only through this oracle.
                    result=search(lambda i:values[i],len(rows),graph,budget,seed,method)
                    result.update(objective=objective,budget=budget,method=method,seed=seed,
                                  optimum=optimum,gap=result['best_score']-optimum,
                                  peak_c=rows[result['best_class']]['peak_c'],
                                  centre_span_mm=rows[result['best_class']]['centre_span_mm'])
                    batch.append(result);runs.append(result)
                summaries.append(dict(objective=objective,budget=budget,method=method,
                    optimum_hit_rate=sum(r['gap']<=1e-12 for r in batch)/len(batch),
                    median_gap=statistics.median(r['gap'] for r in batch),
                    worst_gap=max(r['gap'] for r in batch),
                    mean_proposals=statistics.mean(r['proposals'] for r in batch)))
    pareto=[]
    for r in rows:
        if not any(s['peak_c']<=r['peak_c'] and s['centre_span_mm']<=r['centre_span_mm'] and
                   (s['peak_c']<r['peak_c'] or s['centre_span_mm']<r['centre_span_mm']) for s in rows):
            pareto.append(dict(class_index=r['class_index'],peak_c=r['peak_c'],centre_span_mm=r['centre_span_mm']))
    result=dict(status='finite_domain_baseline_replay_complete',oracle_sha256=hashlib.sha256(raw).hexdigest(),
                oracle_build_seconds=oracle['elapsed_seconds'],classes=len(rows),
                local_move_component_sizes=components(graph),pareto=pareto,
                summaries=summaries,runs=runs,physical_optimum_certified=False,
                scope='offline query-counted algorithm replay; centre-span proxy, not routed wirelength; no runtime speedup or SOTA claim')
    with args.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(dict(components=result['local_move_component_sizes'],pareto=pareto,summaries=summaries),indent=2))


if __name__=='__main__':main()
