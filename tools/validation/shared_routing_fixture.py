"""Declared resource fixtures, not physical chiplet placement benchmarks."""

from dataclasses import replace
from chiplet_floorplanning.routing_graph import Fabric, Net, edge


def scalable(receivers,lanes=8,blocked_clock=False):
    rows=(lanes+1)*receivers
    base=Fabric(7,rows,layers=2)
    nets=[Net(f'data_{r}_{lane}','data',(0,(lanes+1)*r+lane,0),((6,(lanes+1)*r+lane,0),))
          for r in range(receivers) for lane in range(lanes)]
    nets.append(Net('forwarded_clock','clock',(0,rows-1,1),tuple((6,(lanes+1)*r+lanes,1) for r in range(receivers))))
    allowed={(y,0) for y in range(rows) if y%(lanes+1)<lanes}
    if not blocked_clock:
        allowed.add((rows-1,1))
    blocked=frozenset(edge((3,y,layer),(4,y,layer)) for layer in range(2) for y in range(rows) if (y,layer) not in allowed)
    return replace(base,blocked_edges=blocked),tuple(nets)


def shared_bottleneck():
    blocked=frozenset(edge((1,y,0),(2,y,0)) for y in (0,2))
    fabric=Fabric(4,3,blocked_edges=blocked)
    nets=(Net('clock','clock',(0,1,0),((3,0,0),(3,2,0))),)
    route=frozenset(edge(a,b) for a,b in (
        ((0,1,0),(1,1,0)),((1,1,0),(2,1,0)),((2,1,0),(3,1,0)),
        ((3,1,0),(3,0,0)),((3,1,0),(3,2,0))))
    return fabric,nets,{'clock':route}


def greedy_counterexample():
    return Fabric(4,3),(Net('a','data',(0,0,0),((0,2,0),)),Net('b','data',(0,1,0),((2,1,0),)))
