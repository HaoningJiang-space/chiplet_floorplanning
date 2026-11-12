"""Independent polarity-specific RC moments versus saved integrated STA paths."""

import argparse
import json
import math
from pathlib import Path
import re

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve

from chiplet_floorplanning.characterization import digest
from chiplet_floorplanning.floorplanning import write_json
from chiplet_floorplanning.liberty_checks import unique_group
from chiplet_floorplanning.network_reports import NUMBER


def moments(rc, models, transition, resistance_scale=1.):
    cap = np.asarray(rc['node_parasitic_pf']).copy()
    for index, pin in zip(rc['sink_indices'], rc['sink_pins']):
        instance, port = pin.split(':'); model = models[instance]
        cell = unique_group(Path(model['path']).read_text(), 'cell', model['cell'])
        body = unique_group(cell, 'pin', port)
        found = re.search(r'\b'+transition+r'_capacitance\s*:\s*('+NUMBER+')', body)
        if not found:
            found = re.search(r'\bcapacitance\s*:\s*('+NUMBER+')', body)
        cap[index] += float(found[1])
    interior = [n for n in range(len(cap)) if n != rc['source_index']]
    position = {n: i for i, n in enumerate(interior)}
    rows = []; columns = []; values = []
    for edge in rc['conductors']:
        a, b = edge['a'], edge['b']; g = 1/(edge['resistance_ohm']*resistance_scale)
        for n in (a, b):
            if n in position:
                rows.append(position[n]); columns.append(position[n]); values.append(g)
        if a in position and b in position:
            rows.extend((position[a], position[b])); columns.extend((position[b], position[a])); values.extend((-g, -g))
    matrix = coo_matrix((values, (rows, columns)), shape=(len(interior), len(interior))).tocsr()
    time = spsolve(matrix, cap[interior])*.001  # ohm pF -> ns
    return [float(time[position[n]]) for n in rc['sink_indices']]


def compare(receipt, resistance_scale=1.):
    expected = {name: {edge: moments(rc, receipt['models'], edge, resistance_scale)
                      for edge in ('rise', 'fall')} for name, rc in receipt['rc'].items()}
    checks = []
    for key, path in receipt['paths'].items():
        r, lane, _, transition = key.split('_'); p = path['pins']
        for name, incoming, outgoing, index, edge in [
                ('data_'+r+'_'+lane, 'data', 'receive_d', 0, transition),
                ('forwarded_clock', 'trunk', 'branch_input', int(r), 'fall')]:
            m = expected[name][edge][index]
            delay = math.log(2)*m
            slew = p[incoming]['slew_ns']+math.log(4)*m
            resolution = max(1e-9, 4*2**-23*max(abs(p[incoming]['time_ns']), abs(p[outgoing]['time_ns']), 1.))
            checks.append(dict(path=key, channel=name, delay_ns=delay,
                observed_delay_ns=p[outgoing]['delay_ns'], delay_error_ns=abs(delay-p[outgoing]['delay_ns']),
                delay_resolution_ns=resolution, slew_error_ns=abs(slew-p[outgoing]['slew_ns'])))
    return dict(accepted=all(c['delay_error_ns']<=c['delay_resolution_ns'] and c['slew_error_ns']<1e-7 for c in checks),
                checks=len(checks), max_delay_error_ns=max(c['delay_error_ns'] for c in checks),
                max_slew_error_ns=max(c['slew_error_ns'] for c in checks),
                worst_slew=max(checks, key=lambda c: c['slew_error_ns']),
                resolved_delay_observations=sum(c['delay_ns']>c['delay_resolution_ns'] for c in checks))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--additional-run', type=Path, action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    runs = [args.run]+args.additional_run
    reports = [(root, json.loads((root/'report.json').read_text())) for root in runs]
    if not all(report['complete'] for _, report in reports):
        raise ValueError('benchmark must finish before complete channel audit')
    result = dict(input_report_sha256={str(root/'report.json'): digest(root/'report.json') for root in runs}, script_sha256=digest(__file__),
                  cases={}, physical_channel_qualified=False,
                  scope='polarity_specific_Liberty_capacitance_unique_RC_conductors_and_simple_rc_one_pole_only')
    first = None
    for root, row in [(root, row) for root, report in reports for row in report['cases']+report['paired_refinement']]:
        if row['status']!='analyzed':
            continue
        for mode in ('reference', 'feedback'):
            path = root/row['id']/mode/'report.json'; receipt = json.loads(path.read_text())
            if first is None:
                first = receipt
            result['cases'][row['id']+'_'+mode] = dict(report_sha256=digest(path), **compare(receipt))
    result['negative_control_double_resistance'] = compare(first, 2.)
    result['accepted'] = all(c['accepted'] for c in result['cases'].values()) and not result['negative_control_double_resistance']['accepted']
    write_json(args.output, result)
    print(len(result['cases']), 'timing cases', 'accepted', result['accepted'])
    return 0 if result['accepted'] else 1


if __name__=='__main__':
    raise SystemExit(main())
