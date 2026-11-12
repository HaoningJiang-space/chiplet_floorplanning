"""Strict full-network OpenSTA report extraction, independent of edge arithmetic."""

import re
NUMBER = r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?"


def extract(log, receivers, lanes, include_channel_pins=False, core_pins=False):
    if re.search(r'(?mi)^(?:Error|Warning):|invalid command name', log):
        raise ValueError('STA diagnostic or unconstrained path')
    guards = re.findall(r'NETWORK_CHECKS_BEGIN\n(.*?)NETWORK_CHECKS_END', log, re.S)
    if len(guards) != 1 or 'VIOLATED' in guards[0]:
        raise ValueError('missing checks or electrical violation')
    for receiver in range(receivers):
        if not re.search(rf'(?m)^capture_{receiver}\s+.*\(generated\)$', log):
            raise ValueError('missing generated capture clock')
    blocks = re.findall(r'NETWORK_BEGIN (\w+)\n(.*?)NETWORK_END \1', log, re.S)
    wanted = {f'{r}_{l}_{check}_{edge}' for r in range(receivers) for l in range(lanes)
              for check in ('setup', 'hold') for edge in ('rise', 'fall')}
    if len(blocks) != len(wanted) or {k for k,_ in blocks} != wanted:
        raise ValueError('missing, duplicate or unexpected lane path')
    result = {}
    for key, block in blocks:
        receiver, lane, check, transition = key.split('_')
        suffix = receiver+'_'+lane
        for label, instance, clock in (('Startpoint', 'tx_'+suffix, 'launch'),
                                       ('Endpoint', 'rx_'+suffix, 'capture_'+receiver)):
            if block.count(f'{label}: {instance} (rising edge-triggered flip-flop clocked by {clock})') != 1:
                raise ValueError(key+': wrong endpoint or clock')
        if 'Path Type: '+('max' if check == 'setup' else 'min') not in block:
            raise ValueError(key+': wrong min/max path')

        def pin(name, direction):
            rows = re.findall(rf'(?m)^\s*([\d.eE+\-\s]+?)\s+([\^v])\s+{re.escape(name)} \([^)]+\)$', block)
            selected = [row for row in rows if row[1] == direction]
            if len(selected) != 1:
                raise ValueError(key+': missing/duplicate/wrong pin '+name+' '+direction)
            values = [float(v) for v in re.findall(NUMBER, selected[0][0])]
            if len(values) not in (3,4):
                raise ValueError(key+': bad pin fields')
            return dict(time_ns=values[-1], delay_ns=values[-2], slew_ns=values[-3],
                        cap_pf=values[-4] if len(values)==4 else None)

        def event(clock):
            rows = re.findall(rf'(?m)^\s*{NUMBER}\s+({NUMBER})\s+clock {clock} \(rise edge\)$', block)
            if len(rows) != 1:
                raise ValueError(key+': missing/duplicate event')
            return float(rows[0])

        def time(label):
            rows = re.findall(rf'(?m)^\s*({NUMBER})\s+{label}$', block)
            if not rows:
                raise ValueError(key+': missing reported time '+label)
            return float(rows[0])

        direction = '^' if transition == 'rise' else 'v'
        names = {
            'root_launch':('clock_root/Y', '^'), 'bank':('bank_'+receiver+'/Y', '^'),
            'launch_ck':('tx_'+suffix+'/CK', '^'), 'cq':('tx_'+suffix+'/Q', direction),
            'data':('data_cell_'+suffix+'/Y', direction), 'receive_d':('rx_'+suffix+'/D', direction),
            'root_capture':('clock_root/Y', 'v'), 'trunk':('clock_trunk/Y', 'v'),
            'branch':('branch_'+receiver+'_cell/Y', 'v'), 'inverter':('inv_'+receiver+'/Y', '^'),
            'capture_ck':('rx_'+suffix+'/CK', '^')}
        if core_pins:
            names = {k: (name.replace('/CK', '/CLK').replace('/Y', '/X') if k != 'inverter' else name, direction)
                     for k, (name, direction) in names.items()}
        pins = {k:pin(*v) for k,v in names.items()}
        if include_channel_pins:
            pins['branch_input']=pin('branch_'+receiver+'_cell/A','v')
        correction = re.findall(rf'(?m)^\s*({NUMBER})\s+{NUMBER}\s+clock reconvergence pessimism$', block)
        if len(correction) > 1:
            raise ValueError(key+': repeated common-path correction')
        result[key] = dict(launch_edge_ns=event('launch'), capture_edge_ns=event('capture_'+receiver),
            launch_arrival_ns=pins['launch_ck']['time_ns'], data_arrival_ns=time('data arrival time'),
            capture_arrival_ns=pins['capture_ck']['time_ns'], required_ns=time('data required time'),
            slack_ns=time(r'slack \((?:MET|VIOLATED)\)'), signed_common_path_correction_ns=float(correction[0]) if correction else 0., pins=pins)
    return result
