"""Strict reader for real, little-endian ngspice binary transient raw files."""

import numpy as np


def read_real_binary(path, expected_names):
    fields, variables = {}, []
    in_variables = False
    with path.open('rb') as stream:
        for _ in range(10000):
            line = stream.readline()
            if not line:
                raise ValueError('missing binary waveform data')
            text = line.decode('ascii').strip()
            if text == 'Binary:':
                offset = stream.tell()
                break
            if text == 'Variables:':
                in_variables = True
            elif in_variables:
                parts = text.split()
                if len(parts) != 3 or int(parts[0]) != len(variables):
                    raise ValueError('invalid waveform variable header')
                variables.append(parts[1])
            elif ':' in text:
                key, value = text.split(':', 1)
                fields[key.strip()] = value.strip()
        else:
            raise ValueError('waveform header too long')
    if fields.get('Flags') != 'real' or fields.get('Plotname') != 'Transient Analysis':
        raise ValueError('only real transient raw data supported')
    rows, columns = int(fields['No. Points']), int(fields['No. Variables'])
    if rows < 2 or columns != len(expected_names) or variables != expected_names:
        raise ValueError('waveform dimensions or variables do not match the declared circuit')
    if path.stat().st_size != offset + rows * columns * 8:
        raise ValueError('truncated or trailing binary waveform data')
    # np.fromfile closes the file; the verified archive can then replace it on Windows.
    return np.fromfile(path, dtype='<f8', count=rows*columns, offset=offset).reshape(rows, columns)
