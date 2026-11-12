"""Fixture-specific pin mapping over the production unique-conductor exporter."""

import re
from chiplet_floorplanning.routing_graph import audit
from chiplet_floorplanning.shared_parasitics import SPEF_HEADER, tree_rc, spef_tree


def package_spef(fabric,nets,routes,resistance_scale=1.):
    if not audit(fabric,nets,routes)['fabric_legal']:
        raise ValueError('whole package resource audit must pass before export')
    clocks=[n for n in nets if n.kind=='clock']
    if len(clocks)!=1 or clocks[0].name!='forwarded_clock':
        raise ValueError('this fixture export requires one named forwarded clock')
    receivers=len(clocks[0].sinks)
    data=[n for n in nets if n.kind=='data']
    identifiers=[]
    for net in data:
        match=re.fullmatch(r'data_(\d+)_(\d+)',net.name)
        if not match:
            raise ValueError('unsupported data pin mapping')
        identifiers.append(tuple(map(int,match.groups())))
    lanes=max((lane for _,lane in identifiers),default=-1)+1
    if not 1<=receivers<=15 or not 1<=lanes<=8 or set(identifiers)!={(r,l) for r in range(receivers) for l in range(lanes)}:
        raise ValueError('data identities do not cover the declared shared-clock receiver set')
    text=SPEF_HEADER;records={}
    for net in nets:
        rc=tree_rc(fabric,net,routes[net.name],r_ohm_per_mm=.1*resistance_scale,via_r_ohm=.01*resistance_scale)
        if net.kind=='data':
            suffix=net.name.removeprefix('data_')
            name=net.name;source=f'data_cell_{suffix}:Y';sinks=[f'rx_{suffix}:D']
        else:
            name='forwarded';source='clock_trunk:Y';sinks=[f'branch_{r}_cell:A' for r in range(len(net.sinks))]
        text+=spef_tree(name,source,sinks,rc)
        records[net.name]=dict(design_net=name,source_pin=source,sink_pins=sinks,**rc)
    return text,records
