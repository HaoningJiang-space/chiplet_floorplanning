"""Unique-conductor RC trees and independent nodal first-moment checks.

Positive assumed coefficients define a passive numerical fixture, not a
measured channel. A single-pole timing reduction is not an exact RC waveform.
"""

import math
import re
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

from .routing_graph import audit,edge


SPEF_HEADER='''*SPEF "IEEE 1481-1998"
*DESIGN "fabric"
*DATE "frozen-local-fixture"
*VENDOR "chiplet_floorplanning"
*PROGRAM "shared-conductor-export"
*VERSION "1"
*DESIGN_FLOW "NAME_SCOPE LOCAL"
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER [ ]
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY
'''


def tree_rc(fabric,net,edges,r_ohm_per_mm=.1,c_pf_per_mm=.2,via_r_ohm=.01,via_c_pf=.005,sink_cap_pf=.01,
            resistance_factors=None, sink_shunt_pf=0.):
    sink_caps = ([sink_cap_pf]*len(net.sinks) if np.isscalar(sink_cap_pf) else list(sink_cap_pf))
    if len(sink_caps)!=len(net.sinks) or any(not math.isfinite(v) or v<=0 for v in
            (r_ohm_per_mm,c_pf_per_mm,via_r_ohm,via_c_pf,*sink_caps)):
        raise ValueError('positive finite declared parasitic coefficients required')
    if not audit(fabric,(net,),{net.name:edges})['fabric_legal']:
        raise ValueError('parasitics require one legal physical conductor tree')
    if not math.isfinite(sink_shunt_pf) or sink_shunt_pf < 0:
        raise ValueError('package sink shunt capacitance must be finite and nonnegative')
    factors = {edge(*e): 1. for e in edges} if resistance_factors is None else resistance_factors
    if set(factors)!={edge(*e) for e in edges} or any(not math.isfinite(v) or v<=0 for v in factors.values()):
        raise ValueError('one positive resistance factor per unique conductor required')
    nodes=sorted({n for e in edges for n in e});index={n:i for i,n in enumerate(nodes)}
    source=index[net.source];sinks=[index[n] for n in net.sinks]
    cap=np.zeros(len(nodes));conductors=[];adjacency={i:[] for i in range(len(nodes))}
    for a,b in sorted(edges):
        via=a[2]!=b[2];length=fabric.length_mm((a,b))
        r=(via_r_ohm if via else r_ohm_per_mm*length)*factors[edge(a,b)]
        c=via_c_pf if via else c_pf_per_mm*length
        i,j=index[a],index[b];cap[i]+=c/2;cap[j]+=c/2
        conductors.append(dict(a=i,b=j,resistance_ohm=r,capacitance_pf=c,length_mm=length,via=via))
        adjacency[i].append((j,r));adjacency[j].append((i,r))
    cap[sinks]+=sink_shunt_pf
    loaded=cap.copy();loaded[sinks]+=sink_caps
    interior=[i for i in range(len(nodes)) if i!=source];position={n:i for i,n in enumerate(interior)}
    rows=[];cols=[];values=[]
    for e in conductors:
        a,b=e['a'],e['b'];g=1/e['resistance_ohm']
        for n in (a,b):
            if n!=source:
                rows.append(position[n]);cols.append(position[n]);values.append(g)
        if a!=source and b!=source:
            rows.extend((position[a],position[b]));cols.extend((position[b],position[a]));values.extend((-g,-g))
    matrix=coo_matrix((values,(rows,cols)),shape=(len(interior),len(interior))).tocsr()
    # For a unit ideal-voltage step, DC voltages are all one. G*m1=C*1
    # gives the exact first moment; ohm*pF is 0.001 ns.
    moment=spsolve(matrix,loaded[interior]);nodal=np.zeros(len(nodes));nodal[interior]=moment*.001
    residual=float(np.linalg.norm(matrix@moment-loaded[interior])/np.linalg.norm(loaded[interior]))
    parent={source:None};order=[source];parent_r={}
    for n in order:
        for q,r in adjacency[n]:
            if q not in parent:
                parent[q]=n;parent_r[q]=r;order.append(q)
    subtree=loaded.copy()
    for n in reversed(order[1:]):
        subtree[parent[n]]+=subtree[n]
    elmore=np.zeros(len(nodes))
    for n in order[1:]:
        elmore[n]=elmore[parent[n]]+parent_r[n]*subtree[n]*.001
    error=float(abs(nodal-elmore).max())
    if not np.isfinite(nodal).all() or not math.isfinite(residual) or not math.isfinite(error) or residual>1e-10 or error>1e-12 or nodal.min() < -1e-12:
        raise ValueError('independent RC first-moment check failed')
    return dict(nodes=nodes,source_index=source,sink_indices=sinks,conductors=conductors,
        node_parasitic_pf=cap.tolist(),total_parasitic_pf=float(cap.sum()),total_sink_pin_pf=sum(sink_caps),
        total_package_sink_shunt_pf=len(sinks)*sink_shunt_pf,
        first_moment_ns=nodal[sinks].tolist(),tree_first_moment_ns=elmore[sinks].tolist(),
        max_moment_difference_ns=error,nodal_relative_residual=residual,
        single_pole_50pct_delay_ns=(math.log(2)*nodal[sinks]).tolist(),
        single_pole_20_80_slew_increment_ns=(math.log(4)*nodal[sinks]).tolist(),
        physical_channel_qualified=False)


def spef_tree(design_net,source_pin,sink_pins,rc):
    if len(sink_pins)!=len(rc['sink_indices']) or len({source_pin,*sink_pins})!=len(sink_pins)+1:
        raise ValueError('unique source and sink pin mapping required')
    labels={i:f'{design_net}:{i+1}' for i in range(len(rc['nodes']))}
    labels[rc['source_index']]=source_pin
    labels.update(zip(rc['sink_indices'],sink_pins))
    lines=[f'*D_NET {design_net} {rc["total_parasitic_pf"]:.14g}','*CONN',f'*I {source_pin} O']
    lines += [f'*I {pin} I' for pin in sink_pins]
    lines += ['*CAP']+[f'{i+1} {labels[i]} {c:.14g}' for i,c in enumerate(rc['node_parasitic_pf'])]
    lines += ['*RES']+[f'{i+1} {labels[e["a"]]} {labels[e["b"]]} {e["resistance_ohm"]:.14g}' for i,e in enumerate(rc['conductors'])]
    return '\n'.join(lines+['*END',''])

