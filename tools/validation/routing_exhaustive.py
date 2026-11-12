"""Independent, deliberately tiny exhaustive reference for discrete routing."""

from itertools import product


def enumerate_assignments(fabric,nets,max_nodes=16,max_paths=10000,max_states=200000):
    nodes=[n for n in product(range(fabric.nx),range(fabric.ny),range(fabric.layers)) if n not in fabric.blocked_nodes]
    if len(nodes)>max_nodes:
        return dict(status='exhaustive_limit',proven_infeasible=False)
    # Build adjacency independently, not through the production router's graph.
    adjacency={n:[q for q in nodes if sum(abs(a-b) for a,b in zip(n,q))==1 and tuple(sorted((n,q))) not in fabric.blocked_edges] for n in nodes}
    all_terminals={p:net.name for net in nets for p in net.terminals}
    candidates={};path_counts={};states=0
    for net in nets:
        terminal_paths=[]
        for sink in net.sinks:
            paths=[]
            def visit(path):
                if len(paths)>=max_paths:
                    raise OverflowError
                if path[-1]==sink:
                    paths.append(frozenset(tuple(sorted(e)) for e in zip(path,path[1:])));return
                for q in adjacency[path[-1]]:
                    if q not in path and (q not in all_terminals or all_terminals[q]==net.name):
                        visit(path+[q])
            try:
                visit([net.source])
            except OverflowError:
                return dict(status='exhaustive_limit',proven_infeasible=False)
            terminal_paths.append(paths)
        path_counts[net.name]=[len(p) for p in terminal_paths]
        trees=set()
        for choice in product(*terminal_paths):
            states+=1
            if states>max_states:
                return dict(status='exhaustive_limit',proven_infeasible=False)
            edges=frozenset().union(*choice)
            vertices={p for e in edges for p in e}
            # The union of paths from one source is already connected.
            if len(edges)==len(vertices)-1:
                trees.add(edges)
        candidates[net.name]=sorted(trees,key=lambda e:(len(e),sorted(e)))
    witness=None
    def assign(index,occupied,selected):
        nonlocal states,witness
        states+=1
        if states>max_states:
            raise OverflowError
        if index==len(nets):
            witness=dict(selected);return True
        name=nets[index].name
        for edges in candidates[name]:
            vertices={p for e in edges for p in e}
            if not vertices & occupied:
                selected[name]=edges
                if assign(index+1,occupied|vertices,selected):
                    return True
        return False
    try:
        possible=assign(0,set(),{})
    except OverflowError:
        return dict(status='exhaustive_limit',proven_infeasible=False)
    return dict(status='feasible' if possible else 'exhaustive_infeasible',proven_infeasible=not possible,
                routes=witness,complete_simple_path_counts=path_counts,
                candidate_tree_counts={k:len(v) for k,v in candidates.items()},enumerated_states=states,
                scope='declared_finite_graph_only')
