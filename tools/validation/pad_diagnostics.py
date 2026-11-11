"""Source-defined pad measurements and unfitted finite-difference diagnostics."""

from pathlib import Path
import re

import numpy as np

from chiplet_floorplanning.liberty_checks import lookup, read_table
from .pad_spice import crossing_ns, differences

METRICS = ('rise_delay_ns', 'fall_delay_ns', 'rise_slew_ns', 'fall_slew_ns')


def measurement_convention(path):
    text = re.split(r'\bcell\s*\(', Path(path).read_text(), maxsplit=1)[0]

    def number(name):
        matches = re.findall(r'\b' + name + r'\s*:\s*([\d.]+)\s*;', text)
        if len(matches) != 1:
            raise ValueError('missing/ambiguous source measurement attribute: ' + name)
        return float(matches[0])

    if not re.search(r'time_unit\s*:\s*"1ns"', text):
        raise ValueError('only source ns units are admitted')
    if not re.search(r'capacitive_load_unit\(\s*1(?:\.0+)?\s*,\s*\\?\s*"pf"\s*\)', text, re.I):
        raise ValueError('only source pF units are admitted')
    derate = number('slew_derate_from_library')
    if derate != 1:
        raise ValueError('this diagnostic admits only explicit unit slew derate')
    edges = {}
    for edge in ('rise', 'fall'):
        values = {key: number(key + '_' + edge) / 100 for key in (
            'input_threshold_pct', 'output_threshold_pct',
            'slew_lower_threshold_pct', 'slew_upper_threshold_pct')}
        if not all(0 < v < 1 for v in values.values()) or not (
                values['slew_lower_threshold_pct'] < values['slew_upper_threshold_pct']):
            raise ValueError('invalid source thresholds')
        edges[edge] = values
    return dict(time_unit='ns', capacitance_unit='pF', slew_derate=derate, edges=edges)


def source_measurements(wave, convention, input_voltage_v, output_voltage_v):
    """Re-measure already validated noninverting 10/40 ns transient samples."""
    t, vin, vout = np.asarray(wave).T
    t = t * 1e9
    result = {}
    for edge, start, stop, rising in (('rise', 9, 39, True), ('fall', 39, 69, False)):
        values = convention['edges'][edge]
        mask = (t >= start) & (t <= stop)
        times = t[mask]

        def cross(vector, rail, fraction):
            return crossing_ns(times, vector[mask], rail * fraction, rising)

        result[edge + '_delay_ns'] = (
            cross(vout, output_voltage_v, values['output_threshold_pct']) -
            cross(vin, input_voltage_v, values['input_threshold_pct']))
        for label, vector, rail in (('slew_ns', vout, output_voltage_v),
                                     ('input_slew_ns', vin, input_voltage_v)):
            result[edge + '_' + label] = abs(
                cross(vector, rail, values['slew_upper_threshold_pct']) -
                cross(vector, rail, values['slew_lower_threshold_pct']))
    return result


def table_reference(arc, slew_ns, external_load_pf, self_cap_pf, mapping):
    if mapping not in ('external_plus_self', 'external_only'):
        raise ValueError('unknown load mapping')
    axis_load = external_load_pf + (self_cap_pf if mapping == 'external_plus_self' else 0)
    point = [slew_ns, axis_load]
    metrics, domains = {}, {}
    for key in METRICS:
        edge, kind, _ = key.split('_')
        table = read_table(arc, 'cell_' + edge if kind == 'delay' else edge + '_transition')
        inside = all(axis[0] <= value <= axis[-1] for axis, value in zip(table[0], point))
        domains[key] = dict(inside=bool(inside), bounds=[list(map(float, axis[[0, -1]])) for axis in table[0]])
        if inside:
            metrics[key] = lookup(table, point)
    admitted = all(row['inside'] for row in domains.values())
    return dict(mapping=mapping, query=[slew_ns, axis_load], domains=domains,
                in_domain=admitted, metrics=metrics if admitted else None,
                status='in_domain' if admitted else 'table_domain_rejected')


def nominal_comparison(metrics, reference, max_transition_ns):
    if not reference['in_domain']:
        return {**reference, 'agreement': None, 'output_slew_screen': None}
    return {**reference, 'agreement': differences(metrics, reference['metrics'], 0.020, 0.10),
            'output_slew_screen': (None if max_transition_ns is None else dict(
                limit_ns=max_transition_ns,
                measured_passed=all(metrics[e + '_slew_ns'] <= max_transition_ns for e in ('rise', 'fall')),
                liberty_passed=all(reference['metrics'][e + '_slew_ns'] <= max_transition_ns for e in ('rise', 'fall')),
                scope='output slew only, not complete interface electrical qualification'))}


def finite_difference(first, second, first_ref, second_ref, first_step_error, second_step_error):
    """Signed changes with an empirical numerical screen, never offset-corrected."""
    if not first_ref['in_domain'] or not second_ref['in_domain']:
        return dict(status='table_domain_rejected', metrics=None)
    rows = {}
    for metric in METRICS:
        measured = second[metric] - first[metric]
        predicted = second_ref['metrics'][metric] - first_ref['metrics'][metric]
        residual = measured - predicted
        screen = first_step_error[metric] + second_step_error[metric]
        rows[metric] = dict(spice_delta_ns=measured, liberty_delta_ns=predicted,
                            residual_ns=residual, endpoint_step_change_sum_ns=screen,
                            residual_exceeds_observed_step_changes=abs(residual) > screen)
    return dict(status='diagnostic_only', metrics=rows, physical_accuracy_qualified=False)
