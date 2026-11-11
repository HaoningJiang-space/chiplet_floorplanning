"""Strict adapter for the selected measured SKY130 MDM DC sweeps."""

import re
from pathlib import Path

import numpy as np


def read_mdm(path):
    text = Path(path).read_text()
    header = re.search(r'BEGIN_HEADER\s*(.*?)END_HEADER', text, re.S)
    if header is None:
        raise ValueError('missing MDM header')
    inputs = {}
    input_text = header[1].split('ICCAP_INPUTS')[1].split('ICCAP_OUTPUTS')[0]
    for line in input_text.splitlines():
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        if parts[1] != 'V' or name not in ('VD', 'VG', 'VS', 'VB') or name in inputs:
            raise ValueError('unsupported MDM input')
        mode = parts[6]
        if mode == 'CON':
            inputs[name] = np.array([float(parts[7])])
        elif mode == 'LIN':
            start, stop, count, step = float(parts[8]), float(parts[9]), int(parts[10]), float(parts[11])
            values = start + np.arange(count) * step
            if not np.isclose(values[-1], stop, rtol=1e-12, atol=1e-12):
                raise ValueError('inconsistent MDM linear sweep')
            inputs[name] = values
        else:
            raise ValueError('unsupported MDM sweep')
    if set(inputs) != {'VD', 'VG', 'VS', 'VB'}:
        raise ValueError('incomplete four-terminal biases')
    curves = []
    for block in re.findall(r'BEGIN_DB\s*(.*?)END_DB', text, re.S):
        lines = [x.strip() for x in block.splitlines() if x.strip()]
        fixed = {}
        columns, rows = None, []
        for line in lines:
            if line.startswith('ICCAP_VAR'):
                _, name, value = line.split()
                if name in fixed:
                    raise ValueError('duplicate MDM fixed bias')
                fixed[name] = float(value)
            elif line.startswith('#'):
                if columns is not None:
                    raise ValueError('duplicate MDM columns')
                columns = line[1:].split()
            else:
                rows.append([float(x) for x in line.split()])
        if columns is None or len(columns) != 4 or set(columns[1:]) != {'ID', 'IG', 'IB'}:
            raise ValueError('unexpected MDM output columns')
        sweep = columns[0]
        if sweep not in inputs or set(fixed) != set(inputs) - {sweep}:
            raise ValueError('ambiguous MDM bias definition')
        a = np.array(rows)
        if a.shape != (len(inputs[sweep]), 4) or not np.all(np.isfinite(a)):
            raise ValueError('invalid MDM DB shape or values')
        if not np.allclose(a[:, 0], inputs[sweep], rtol=1e-12, atol=1e-12):
            raise ValueError('MDM sweep does not match header')
        if any(not np.any(np.isclose(inputs[k], value, atol=1e-12, rtol=1e-12)) for k, value in fixed.items()):
            raise ValueError('MDM fixed bias outside header')
        curves.append(dict(sweep=sweep, fixed=fixed,
                           columns={k: a[:, j] for j, k in enumerate(columns)}))
    if not curves:
        raise ValueError('no MDM curves')
    expected = int(np.prod([len(v) for k, v in inputs.items() if k != curves[0]['sweep']]))
    keys = [(c['sweep'], tuple(sorted(c['fixed'].items()))) for c in curves]
    if len(set(keys)) != len(curves) or len(curves) != expected:
        raise ValueError('incomplete or duplicate MDM curve set')
    return curves


def deck(curves, model_root, device, temperature_c):
    lines = ['Measured primitive conditional TT diagnostic; not Pad qualification',
             f'.lib "{model_root.as_posix()}/sky130A/libs.tech/ngspice/sky130.lib.spice" tt',
             'VD d 0 0', 'VG g 0 0', 'VS s 0 0', 'VB b 0 0',
             f'Xdut d g s b sky130_fd_pr__{device} w=7 l=0.5 m=1',
             f'.temp {temperature_c}', '.options reltol=1e-7 abstol=1e-14 vntol=1e-9',
             '.control', 'set numdgt=16', 'set wr_singlescale', 'set wr_vecnames']
    for index, curve in enumerate(curves):
        for key, value in curve['fixed'].items():
            lines.append(f'alter {key} {value:.15g}')
        x = curve['columns'][curve['sweep']]
        lines += [f'dc {curve["sweep"]} {x[0]:.15g} {x[-1]:.15g} {x[1]-x[0]:.15g}',
                  f'wrdata curve-{index:02d}.txt i(vd) i(vg) i(vs) i(vb) v(d) v(g) v(s) v(b)']
    return '\n'.join(lines + ['quit', '.endc', '.end']) + '\n'


def compare(curve, samples):
    x = curve['columns'][curve['sweep']]
    a = np.atleast_2d(samples)
    if a.shape != (len(x), 9) or not np.all(np.isfinite(a)):
        raise ValueError('invalid DC simulation output')
    if not np.allclose(a[:, 0], x, atol=1e-10, rtol=1e-10):
        raise ValueError('simulation and measurement bias coordinates differ')
    expected_v = np.column_stack([x if name == curve['sweep'] else np.full(len(x), curve['fixed'][name])
                                  for name in ['VD', 'VG', 'VS', 'VB']])
    if not np.allclose(a[:, 5:9], expected_v, atol=1e-10, rtol=1e-10):
        raise ValueError('terminal voltages do not match measurement')
    currents = -a[:, 1:5]  # SPICE voltage-source current -> into device
    measured = curve['columns']['ID']
    error = currents[:, 0] - measured
    on = np.abs(measured) >= 1e-5
    power = np.sum(currents * a[:, 5:9], axis=1)
    return dict(points=len(x), id_rmse_a=float(np.sqrt(np.mean(error**2))),
                id_max_abs_error_a=float(np.max(np.abs(error))),
                id_normalized_rmse=float(np.sqrt(np.mean(error**2)) / max(float(np.max(np.abs(measured))), 1e-9)),
                on_state_count=int(on.sum()), on_state_rmse_a=float(np.sqrt(np.mean(error[on]**2))) if np.any(on) else None,
                model_kcl_inf_a=float(np.max(np.abs(currents.sum(axis=1)))),
                model_minimum_port_power_w=float(np.min(power)),
                model_maximum_port_power_w=float(np.max(power)),
                model_kcl_screen=bool(np.max(np.abs(currents.sum(axis=1))) < 1e-10),
                model_power_screen=bool(np.min(power) >= -1e-12))
