"""Finite-width discrete routing resources with explicit shared-net identity.

This is a declared grid-fabric contract, not a foundry/package routing signoff.
Node capacity one prevents touching/crossing different nets on the same layer.
Uniform pitch and landing-size bounds supply clearance between distinct nodes.
"""

from dataclasses import dataclass
import heapq
import math


def edge(a, b):
    return tuple(sorted((tuple(a), tuple(b))))


@dataclass(frozen=True)
class Fabric:
    nx: int
    ny: int
    layers: int = 1
    pitch_um: float = 20.
    width_um: float = 10.
    spacing_um: float = 10.
    via_landing_um: float = 10.
    layer_separation_um: float = 30.
    edge_clearance_um: float = 10.
    blocked_nodes: frozenset = frozenset()
    blocked_edges: frozenset = frozenset()

    def __post_init__(self):
        if any(type(n) is not int or n < 1 for n in (self.nx, self.ny, self.layers)):
            raise ValueError('positive integer grid dimensions required')
        if self.nx*self.ny*self.layers > 200000:
            raise ValueError('declared fabric exceeds implementation resource limit')
        if any(not math.isfinite(x) or x <= 0 for x in (self.pitch_um,self.width_um,self.spacing_um,self.via_landing_um,self.layer_separation_um,self.edge_clearance_um)):
            raise ValueError('positive finite physical dimensions required')
        if self.pitch_um+1e-12 < max(self.width_um,self.via_landing_um)+self.spacing_um:
            raise ValueError('pitch cannot provide conductor/landing spacing')
        for n in self.blocked_nodes:
            if not self.in_bounds(n):
                raise ValueError('blocked node outside fabric')
        for a,b in self.blocked_edges:
            if not self.in_bounds(a) or not self.in_bounds(b) or sum(abs(x-y) for x,y in zip(a,b)) != 1 or edge(a,b) != (a,b):
                raise ValueError('blocked edge must be a canonical adjacent resource')

    def in_bounds(self, n):
        return len(n)==3 and all(type(x) is int and 0 <= x < limit for x,limit in zip(n,(self.nx,self.ny,self.layers)))

    def allowed(self,n):
        return self.in_bounds(n) and n not in self.blocked_nodes

    def neighbors(self,n):
        if not self.allowed(n):
            return
        for axis in range(3):
            for delta in (-1,1):
                q=list(n);q[axis]+=delta;q=tuple(q)
                if self.allowed(q) and edge(n,q) not in self.blocked_edges:
                    yield q

    def length_mm(self,e):
        return (self.layer_separation_um if e[0][2] != e[1][2] else self.pitch_um)/1000.

    def coordinates_mm(self,n):
        margin=max(self.width_um,self.via_landing_um)/2+self.edge_clearance_um
        return ((margin+n[0]*self.pitch_um)/1000,(margin+n[1]*self.pitch_um)/1000,n[2]*self.layer_separation_um/1000)


@dataclass(frozen=True)
class Net:
    name: str
    kind: str
    source: tuple
    sinks: tuple

    @property
    def terminals(self):
        return (self.source,)+self.sinks


def validate_inputs(fabric,nets):
    names=set();owners={}
    if not nets:
        raise ValueError('routing needs at least one physical net')
    for net in nets:
        if not isinstance(net.name,str) or not net.name or net.name in names or net.kind not in ('data','clock'):
            raise ValueError('unique names and declared data/clock kinds required')
        names.add(net.name)
        if not net.sinks or len(set(net.terminals)) != len(net.terminals) or (net.kind=='data' and len(net.sinks)!=1):
            raise ValueError('distinct terminals required; data nets are point-to-point')
        for terminal in net.terminals:
            if not fabric.allowed(terminal):
                raise ValueError('terminal unavailable or outside fabric')
            if terminal in owners:
                raise ValueError('different nets cannot own one physical terminal')
            owners[terminal]=net.name
    return owners


def audit(fabric,nets,routes):
    validate_inputs(fabric,nets)
    issues=[];occupancy={};records={}
    if set(routes) != {n.name for n in nets}:
        issues.append('route IDs differ from physical nets')
    for net in nets:
        supplied=routes.get(net.name,())
        edges={edge(*e) for e in supplied}
        if len(edges)!=len(supplied):
            issues.append(net.name+': repeated physical edge')
        adjacency={}
        for a,b in edges:
            if b not in set(fabric.neighbors(a)):
                issues.append(net.name+': blocked or nonadjacent resource')
            adjacency.setdefault(a,set()).add(b);adjacency.setdefault(b,set()).add(a)
        found=set();stack=[net.source]
        while stack:
            n=stack.pop()
            if n in found:
                continue
            found.add(n);stack.extend(adjacency.get(n,()))
        if not set(net.terminals).issubset(found) or found != set(adjacency):
            issues.append(net.name+': disconnected terminal/conductor')
        if len(edges)!=len(adjacency)-1:
            issues.append(net.name+': conductor graph is not a tree')
        if any(len(adj)==1 and n not in net.terminals for n,adj in adjacency.items()):
            issues.append(net.name+': dangling nonterminal conductor')
        for n in adjacency:
            occupancy.setdefault(n,set()).add(net.name)
        # Tree path length is diagnostic only. Physical length is the edge union.
        distances={net.source:0.};queue=[net.source]
        for n in queue:
            for q in adjacency.get(n,()):
                if q not in distances:
                    distances[q]=distances[n]+fabric.length_mm(edge(n,q));queue.append(q)
        records[net.name]=dict(kind=net.kind,physical_edges=len(edges),physical_nodes=len(adjacency),
            unique_wire_length_mm=sum(fabric.length_mm(e) for e in edges if e[0][2]==e[1][2]),
            via_count=sum(e[0][2]!=e[1][2] for e in edges),
            unique_total_length_mm=sum(fabric.length_mm(e) for e in edges),
            sum_source_sink_path_length_mm=sum(distances.get(s,0.) for s in net.sinks),
            sink_count=len(net.sinks))
    conflicts={str(n):sorted(ids) for n,ids in occupancy.items() if len(ids)>1}
    if conflicts:
        issues.append('different nets share conductor nodes or edges')
    return dict(fabric_legal=not issues,issues=issues,node_conflicts=conflicts,nets=records,
                occupied_node_count=len(occupancy),complete_package_signoff=False,
                scope='finite_width_declared_track_grid_only_no_bump_escape_return_path_or_extraction')


def route_greedy(fabric,nets,order=None):
    terminals=validate_inputs(fabric,nets)
    by_name={n.name:n for n in nets}
    order=list(by_name) if order is None else list(order)
    if len(order)!=len(by_name) or set(order)!=set(by_name):
        raise ValueError('routing order must name each physical net exactly once')
    occupied=set();routes={}
    for name in order:
        net=by_name[name];tree={net.source};selected=set()
        forbidden=occupied|{n for n,owner in terminals.items() if owner!=name}
        for target in net.sinks:
            if target in tree:
                continue
            distance={n:0. for n in tree};parent={};queue=[(0.,n) for n in tree];heapq.heapify(queue)
            reached=False
            while queue:
                cost,n=heapq.heappop(queue)
                if cost!=distance[n]:
                    continue
                if n==target:
                    reached=True;break
                for q in fabric.neighbors(n):
                    if q in forbidden:
                        continue
                    candidate=round(cost+fabric.length_mm(edge(n,q)),12)
                    if candidate < distance.get(q,float('inf')):
                        distance[q]=candidate;parent[q]=n;heapq.heappush(queue,(candidate,q))
            if not reached:
                return dict(status='search_failed',failed_net=name,routes=routes,proven_infeasible=False)
            n=target
            while n not in tree:
                q=parent[n];selected.add(edge(n,q));tree.add(n);n=q
        routes[name]=selected;occupied.update(tree)
    result=audit(fabric,nets,routes)
    if not result['fabric_legal']:
        raise RuntimeError('router emitted an invalid tree assignment')
    return dict(status='feasible',routes=routes,audit=result,proven_infeasible=False)


def cut_certificate(fabric,nets,x_split):
    validate_inputs(fabric,nets)
    if type(x_split) is not int or not 0 <= x_split < fabric.nx-1:
        raise ValueError('invalid complete x-section')
    crossing=[]
    for layer in range(fabric.layers):
        for y in range(fabric.ny):
            a=(x_split,y,layer);b=(x_split+1,y,layer)
            if b in set(fabric.neighbors(a)):
                crossing.append(edge(a,b))
    demand=[n.name for n in nets if {p[0]<=x_split for p in n.terminals}=={True,False}]
    return dict(x_split=x_split,crossing_edges=crossing,capacity=len(crossing),
                distinct_crossing_nets=demand,demand=len(demand),
                proven_infeasible=len(demand)>len(crossing),scope='declared_fabric_only')


def verify_cut(fabric,nets,certificate):
    # Recompute the entire cut and demand; a caller cannot omit an available
    # layer/edge or count the same multi-sink clock repeatedly.
    expected=cut_certificate(fabric,nets,certificate['x_split'])
    def canonical(value):
        import json
        return json.dumps(value,sort_keys=True)
    if canonical(certificate)!=canonical(expected):
        raise ValueError('cut certificate does not match the complete fabric')
    return expected['proven_infeasible']
