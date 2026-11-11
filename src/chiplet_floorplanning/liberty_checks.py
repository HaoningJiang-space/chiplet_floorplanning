"""Independent bounded lookup of the four active GPIO pad timing arcs.

This deliberately supports the pinned NLDM cells and fixed modes only. It is
not a general Liberty parser or a transistor-level waveform validation.
"""

from pathlib import Path
import re

import numpy as np
from scipy.interpolate import RegularGridInterpolator


def groups(text, kind):
    for match in re.finditer(r'\b'+re.escape(kind)+r'\s*\(([^()]*)\)\s*\{', text):
        start = match.end()
        depth, quoted, escaped = 1, False, False
        for i in range(start, len(text)):
            char = text[i]
            if escaped:
                escaped = False
            elif char == '\\' and quoted:
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted:
                depth += (char == '{')-(char == '}')
                if depth == 0:
                    yield match[1].strip().strip('"'), text[start:i]
                    break
        else:
            raise ValueError('unterminated Liberty group')


def unique_group(text, kind, name):
    found = [body for key, body in groups(text, kind) if key == name]
    if len(found) != 1:
        raise ValueError(f'missing or ambiguous Liberty {kind} {name}')
    return found[0]


def read_table(arc, kind):
    found = list(groups(arc, kind))
    if len(found) != 1:
        raise ValueError('missing or ambiguous pad lookup table')
    text = found[0][1]
    def rows(name):
        match = re.search(r'\b'+name+r'\s*\((.*?)\)\s*;', text, re.S)
        if not match:
            raise ValueError('missing table values or axes')
        return [[float(v.strip()) for v in row.split(',')]
                for row in re.findall(r'"([^\"]*)"', match[1])]
    axes = [np.asarray(rows(key)[0]) for key in ('index_1', 'index_2')]
    values = np.asarray(rows('values'))
    if (values.shape != tuple(len(a) for a in axes) or not np.all(np.isfinite(values))
            or any(not np.all(np.isfinite(a)) or not np.all(np.diff(a) > 0) for a in axes)):
        raise ValueError('invalid pad table')
    return axes, values


def lookup(table, point, bounded=True):
    axes, values = table
    if not np.all(np.isfinite(point)):
        raise ValueError('nonfinite pad table query')
    if bounded and any(p < a[0] or p > a[-1] for p, a in zip(point, axes)):
        raise ValueError('active pad lookup outside characterized slew/load table domain')
    return float(RegularGridInterpolator(axes, values, bounds_error=False, fill_value=None)([point])[0])


def active_arc(path, cell, pin, condition):
    body = unique_group(unique_group(Path(path).read_text(), 'cell', cell), 'pin', pin)
    normalize = lambda s: re.sub(r'[\s()]', '', s)
    arcs = []
    for _, arc in groups(body, 'timing'):
        when = re.search(r'\bwhen\s*:\s*"([^\"]*)"', arc)
        if when and normalize(when[1]) == normalize(condition) and list(groups(arc, 'cell_rise')):
            arcs.append(arc)
    if len(arcs) != 1:
        raise ValueError('missing or ambiguous active GPIO mode timing arc')
    return arcs[0]


def check_pad_tables(log, sky_path, gf_path):
    """Match active source tables to report_dcalc, which also prints inactive arcs.

    Identify the matching table by both delay and slew. Extrapolation is used
    only to identify a diagnostic section; acceptance requires an in-domain
    lookup. PDK table axes are used unchanged, including GF pad self-capacitance.
    """
    definitions = {
        'tx': (gf_path, 'gf180mcu_fd_io__bi_t', 'PAD', '!IE&OE&PDRV0&PDRV1&!SL', 'A'),
        'rx': (sky_path, 'sky130_ef_io__gpiov2_pad', 'IN', '!IB_MODE_SEL&!VTRIP_SEL', 'PAD'),
    }
    report = []
    for side, (path, cell, pin, condition, source) in definitions.items():
        arc = active_arc(path, cell, pin, condition)
        for lane in ('data', 'clock'):
            instance = f'{side}_{lane}_pad'
            for mode in ('max', 'min'):
                begin, end = f'PAD_ARC_BEGIN {instance} {mode}', f'PAD_ARC_END {instance} {mode}'
                if log.count(begin) != 1 or log.count(end) != 1:
                    raise ValueError('missing pad delay calculation diagnostic')
                section = log.split(begin)[1].split(end)[0]
                for edge, symbol in (('rise', '^'), ('fall', 'v')):
                    delay_table, slew_table = read_table(arc, 'cell_'+edge), read_table(arc, edge+'_transition')
                    pattern = re.escape(f'{source} {symbol} -> {pin} {symbol}')+r'\n(.*?)(?=\.{10}|\Z)'
                    candidates = []
                    for match in re.finditer(pattern, section, re.S):
                        body = match[1]
                        def value(name):
                            found = re.search(re.escape(name)+r' = ([-+0-9.eE]+)', body)
                            if not found:
                                raise ValueError('incomplete pad delay diagnostic')
                            return float(found[1])
                        point = [value('input_net_transition'), value('total_output_net_capacitance')]
                        delay, slew = value('Delay'), value('Slew')
                        errors = [abs(lookup(delay_table, point, False)-delay), abs(lookup(slew_table, point, False)-slew)]
                        if max(errors) <= 3e-6:
                            candidates.append((point, delay, slew, errors))
                    if len(candidates) != 1:
                        raise ValueError(f'active source pad table did not uniquely match STA: {instance} {mode} {edge}')
                    point, delay, slew, errors = candidates[0]
                    lookup(delay_table, point)
                    lookup(slew_table, point)
                    report.append({'instance': instance, 'mode': mode, 'edge': edge, 'condition': condition,
                                   'input_slew_ns': point[0], 'effective_load_pf': point[1],
                                   'delay_ns': delay, 'table_output_slew_ns': slew, 'max_lookup_error_ns': max(errors),
                                   'inside_source_table_domain': True, 'used_in_reported_path': False})
    # A valid inactive report_dcalc table is not evidence that STA propagated
    # the configured mode. Check the pad outputs in both expanded paths too.
    for mode in ('min', 'max'):
        marker = f'Path Type: {mode}\n'
        if log.count(marker) != 1:
            raise ValueError('missing or ambiguous expanded lane path')
        path = log.split(marker)[1].split('DCALC_TX_DATA_BEGIN')[0].split('Startpoint:')[0]
        for side, (_, _, pin, _, _) in definitions.items():
            for lane in ('data', 'clock'):
                instance = f'{side}_{lane}_pad'
                pattern = (r'^\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+[-+0-9.eE]+\s+([\^v])\s+'
                           +re.escape(instance+'/'+pin)+r'\s+\(')
                matches = re.findall(pattern, path, re.M)
                if len(matches) != 1:
                    raise ValueError('missing active pad in expanded lane path')
                slew, delay, transition = matches[0]
                arc_mode = ('min' if mode == 'max' else 'max') if lane == 'clock' else mode
                edge = 'rise' if transition == '^' else 'fall'
                record = next(r for r in report if (r['instance'], r['mode'], r['edge']) == (instance, arc_mode, edge))
                # DMP uses an RC waveform for TX driver slew, while
                # report_dcalc prints NLDM table slew at Ceff. They are
                # distinct quantities (DmpCeff.cc, DmpPi::gateDelaySlew).
                errors = [abs(float(delay)-record['delay_ns'])]
                if side == 'rx':
                    errors.append(abs(float(slew)-record['table_output_slew_ns']))
                if max(errors) > 5e-6:
                    raise ValueError('expanded path does not use the configured active pad timing table')
                record['used_in_reported_path'] = True
                record['propagated_output_slew_ns'] = float(slew)
                record['path_delay_error_ns'] = abs(float(delay)-record['delay_ns'])
    return report
