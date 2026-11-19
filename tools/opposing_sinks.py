"""Test the two-terminal temperature identity and the common-cooling limit on passive networks."""

import argparse
from itertools import permutations, product
import json
from pathlib import Path

import numpy as np


def network(coords, graded):
    xy = np.asarray(coords)
    lap = np.zeros((len(xy),len(xy)))
    for i, j in zip(*np.where(np.triu(abs(xy[:,None]-xy).sum(2)==1,1))):
        conductance = 1 / (1+.25*((int(i)+3*int(j))%5)) if graded else 1.
        lap[i,i] += conductance
        lap[j,j] += conductance
        lap[i,j] = lap[j,i] = -conductance
    return lap


def temperatures(lap, sink, watts):
    free = np.arange(len(lap)) != sink
    t = np.zeros(len(lap))
    t[free] = np.linalg.solve(lap[np.ix_(free,free)],watts[free])
    assert abs((watts - lap@t)[sink]-watts.sum()) < 1e-10
    return t


def compare(coords, terminals, graded, powers):
    xy = np.array(coords)
    lap = network(xy,graded)
    a,b = terminals
    phi = temperatures(lap,a,np.eye(len(lap))[b])
    resistance = phi[b]
    layouts = list(permutations((i for i in range(len(lap)) if i not in terminals),2))
    h, exposed, cost = [], [], []
    error = 0.
    for pose in layouts:
        w = np.zeros(len(lap))
        w[list(pose)] = powers
        ta,tb = temperatures(lap,a,w),temperatures(lap,b,w)
        error = max(error,abs(ta[b]-phi@w),abs(tb[a]-(resistance-phi)@w))
        h.append([ta.max(),tb.max()])
        exposed.append([ta[b],tb[a]])
        cost.append(abs(xy[pose[0]]-xy[pose[1]]).sum())
    h, exposed = np.array(h), np.array(exposed)
    layouts, cost = np.array(layouts), np.array(cost)
    ceiling = (h.sum(axis=1)-sum(powers)*resistance)/2
    assert error < 1e-10 and ceiling.min() >= -1e-10
    possible = moves = 0
    best_per_start = []
    max_violation = 0.
    for i, pose in enumerate(layouts):
        feasible = ((layouts==pose).any(axis=1) | (layouts==pose[::-1]).all(axis=1)) & (cost<=cost[i])
        gains = (h[i]-h[feasible]).min(axis=1)
        deficit = h[i]-exposed[i]
        delta = exposed[feasible]-exposed[i]
        bound = (deficit-delta).min(axis=1)
        max_violation = max(max_violation,float((gains-bound).max()),float(gains.max()-ceiling[i]))
        best_per_start.append(gains.max())
        possible += int(gains.max() > 1e-9)
        moves += int(feasible.sum()-1)
    assert max_violation < 1e-10
    return dict(terminals=terminals, nodes=len(lap), powers_w=powers, heterogeneous=graded,
                resistance_k_w=float(resistance), starts=len(layouts), finite_moves=moves,
                common_cooling_possible=possible, zero_ceiling=int((ceiling<1e-9).sum()),
                positive_ceiling_but_stuck=int(((ceiling>1e-9)&(np.array(best_per_start)<1e-9)).sum()),
                max_common_reduction_k=float(max(best_per_start)), max_port_identity_error_k=float(error),
                max_gain_above_bound_k=max_violation)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output",type=Path,required=True)
    args = ap.parse_args()
    line = [(i,0,0) for i in range(7)]
    cases = {"chain":(line,(0,6)), "branch":(line+[(3,1,0),(3,2,0)],(0,6)),
             "mesh":(list(product(range(3),range(3),range(1))),(0,8)),
             "volume":(list(product(range(3),range(2),range(2))),(0,11))}
    observations = {n:[compare(xy,t,g,p) for g,p in product((False,True),([1.,3.],[2.,2.]))]
                    for n,(xy,t) in cases.items()}
    # Hand-checkable fork: the same watt is moved from a spur onto a wire between two contacts.
    fork = network([(0,0),(1,0),(2,0),(1,1)],False)
    witnesses = [[float(temperatures(fork,sink,np.eye(4)[source]).max()) for sink in (0,2)] for source in (3,1)]
    assert np.allclose(witnesses,[[2,2],[1,1]])
    # Four outer contacts connect to a common junction v. The centre contact connects via u to v.
    # The same source moving u -> v is farther from the centre and closer to all four outer contacts.
    incidence = np.zeros((6,7))
    for i,(j,k) in enumerate(((0,1),(1,2),(2,3),(2,4),(2,5),(2,6))):
        incidence[i,j],incidence[i,k] = 1.,-1.
    star = incidence.T @ incidence
    holdout = [[float(temperatures(star,s,np.eye(7)[u]).max()) for s in (3,4,5,6,0)] for u in (1,2)]
    assert np.allclose(holdout,[[2,2,2,2,1],[1,1,1,1,2]])
    result = dict(networks=observations,unit_fork_peaks_k=witnesses,
                  four_outer_and_one_centre_peaks_k=holdout,
                  old_hotspot_only=dict(resistance_k_w=1, starting_power_w=[2,1], moved_power_w=[0,3],
                                        old_cell_cooling_k=2, global_cooling_k=-1))
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8",newline="\n")


if __name__ == "__main__":
    main()
