"""Restricted public JSON-Liberty assembly and bracketed table interpolation.

No timing values are invented by the renderer. Interpolation is an explicit
approximation, not additional foundry characterization or physical calibration.
"""

import copy
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from scipy.interpolate import RegularGridInterpolator

from .model import fields, identifier, number


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scalar(value):
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return str(value).lower()
    return format(number(value, 'Liberty scalar'), '.12g')


def render_json_liberty(data, indent='    '):
    """Render the public PDK JSON grammar used by the selected cells.

    Fail on unsupported structures rather than silently dropping attributes.
    """
    lines = []
    for key in sorted(data, key=lambda k: k == 'default_operating_conditions'):
        value = data[key]
        fields = key.split(',')
        if fields[0] == 'comp_attribute':
            name = fields[1]
            if isinstance(value, dict):
                rows = list(value.items())
            elif isinstance(value, list) and value and isinstance(value[0], list):
                rows = value
            else:
                rows = [value if isinstance(value, list) else [value]]
            lines += [f'{indent}{name}('+', '.join(scalar(x) for x in row)+');' for row in rows]
        elif key == 'define':
            for row in value:
                lines.append(indent+'define('+', '.join(scalar(row[k]) for k in
                             ('attribute_name', 'group_name', 'attribute_type'))+');')
        elif isinstance(value, dict) or (isinstance(value, list) and value and isinstance(value[0], dict)):
            for group in value if isinstance(value, list) else [value]:
                args = ', '.join(scalar(x) for x in fields[1:])
                lines.append(f'{indent}{fields[0]}({args}) {{')
                lines.append(render_json_liberty(group, indent+'    '))
                lines.append(indent+'}')
        elif isinstance(value, list):
            if fields[0] not in ('index_1', 'index_2', 'index_3', 'values'):
                raise ValueError(f'unsupported JSON Liberty list: {key}')
            rows = value if value and isinstance(value[0], list) else [value]
            lines.append(indent+key+'('+', '.join(json.dumps(', '.join(scalar(x) for x in row)) for row in rows)+');')
        else:
            if len(fields) != 1:
                raise ValueError(f'unsupported JSON Liberty field: {key}')
            lines.append(f'{indent}{key} : {scalar(value)};')
    return '\n'.join(lines)


def interpolate_cell(low, high, fraction, path='cell'):
    """Match topology; regrid on axis intersection; use conservative limits."""
    number(fraction, 'interpolation fraction', minimum=0)
    if fraction > 1:
        raise ValueError('temperature extrapolation is forbidden')
    if type(low) is not type(high) and not (isinstance(low, (int, float)) and isinstance(high, (int, float))):
        raise ValueError(f'temperature table structure mismatch: {path}')
    if isinstance(low, dict):
        if low.keys() != high.keys():
            raise ValueError(f'temperature table fields mismatch: {path}')
        axes = [f'index_{i}' for i in (1, 2, 3) if f'index_{i}' in low]
        if axes and 'values' in low and any(low[k] != high[k] for k in axes):
            if fraction in (0, 1):
                return copy.deepcopy(low if fraction == 0 else high)
            common_axes = []
            for key in axes:
                a, b = (np.asarray(table[key], dtype=float) for table in (low, high))
                if not all(np.all(np.isfinite(x)) and np.all(np.diff(x) > 0) for x in (a, b)):
                    raise ValueError('nonmonotonic/nonfinite Liberty table axis')
                left, right = max(a[0], b[0]), min(a[-1], b[-1])
                if left >= right:
                    raise ValueError('temperature tables have no common interpolation domain')
                values = np.unique(np.concatenate((a, b)))
                common_axes.append(values[(values >= left) & (values <= right)])
            points = np.stack(np.meshgrid(*common_axes, indexing='ij'), axis=-1)
            tables = []
            for table in (low, high):
                grid = tuple(table[key] for key in axes)
                values = np.asarray(table['values'], dtype=float).reshape(tuple(len(g) for g in grid))
                tables.append(RegularGridInterpolator(grid, values, bounds_error=True)(points))
            result = {k: interpolate_cell(low[k], high[k], fraction, path+'/'+k)
                      for k in low if k not in axes and k != 'values'}
            result.update({key: values.tolist() for key, values in zip(axes, common_axes)})
            result['values'] = (tables[0]+fraction*(tables[1]-tables[0])).tolist()
            return result
        result = {}
        for key in low:
            if key.startswith('index_') and low[key] != high[key]:
                raise ValueError(f'temperature table axes mismatch: {path}/{key}')
            result[key] = interpolate_cell(low[key], high[key], fraction, path+'/'+key)
        return result
    if isinstance(low, list):
        if len(low) != len(high):
            raise ValueError(f'temperature table shape mismatch: {path}')
        if low and isinstance(low[0], dict):
            # Upstream leakage groups can be reordered between temperatures.
            # Match by Boolean conditions and other symbolic attributes, never
            # by magnitude or position in the serialized file.
            def symbolic(value):
                if isinstance(value, dict):
                    return {k: symbolic(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [symbolic(v) for v in value]
                return value if isinstance(value, str) else None
            def identity(value):
                return json.dumps(symbolic(value), sort_keys=True)
            other = {identity(v): v for v in high}
            if len(other) != len(high) or len({identity(v) for v in low}) != len(low):
                raise ValueError(f'ambiguous repeated temperature groups: {path}')
            if {identity(v) for v in low} != other.keys():
                raise ValueError(f'temperature group conditions mismatch: {path}')
            high = [other[identity(v)] for v in low]
        return [interpolate_cell(a, b, fraction, path) for a, b in zip(low, high)]
    if isinstance(low, (int, float)) and not isinstance(low, bool):
        number(low, path)
        number(high, path)
        if fraction == 0:
            return low
        if fraction == 1:
            return high
        if path.rsplit('/', 1)[-1] in ('max_capacitance', 'max_transition', 'max_fanout'):
            return min(low, high)
        if path.rsplit('/', 1)[-1] in ('min_capacitance', 'min_transition'):
            return max(low, high)
        return low + fraction*(high-low)
    if low != high:
        raise ValueError(f'temperature table semantic mismatch: {path}')
    return low


def sky_header(root, corner):
    root = Path(root)
    header = json.loads((root/'sky_common.json').read_text())
    header.update(json.loads((root/f'sky_{corner}.json').read_text()))
    return header


def write_sky_library(root, corner, output):
    header = sky_header(root, corner)
    for cell in ('buf_8', 'dfxtp_1'):
        header['cell,sky130_fd_sc_hd__'+cell] = json.loads((Path(root)/f'sky_{cell}_{corner}.json').read_text())
    content = 'library("sky_'+corner+'") {\n'+render_json_liberty(header)+'\n}\n'
    Path(output).write_text(content)


def sample_instance_temperature(case, grid_c, die_id, point_mm):
    """Use the containing thermal cell centre value; no smoothing over voids."""
    die = next((die for die in case.dies if die.id == die_id), None)
    if die is None or not isinstance(point_mm, list) or len(point_mm) != 2:
        raise ValueError('unknown die or invalid local point')
    x, y = [number(v, 'instance position', minimum=0) for v in point_mm]
    if x >= die.width or y >= die.height:
        raise ValueError('instance point must be inside the die')
    gx, gy = die.point(x, y)
    # A rotated local origin may lie on the high edge. Probe an infinitesimal
    # distance toward the die centre to choose the die-side cell at boundaries.
    cx, cy = die.point(die.width/2, die.height/2)
    gx, gy = np.nextafter(gx, cx), np.nextafter(gy, cy)
    ix, iy = math.floor(gx/case.package.width*case.nx), math.floor(gy/case.package.height*case.ny)
    grid_c = np.asarray(grid_c)
    if grid_c.shape != (case.ny, case.nx):
        raise ValueError('temperature grid shape mismatch')
    value = float(grid_c[iy, ix])
    if not math.isfinite(value):
        raise ValueError('instance temperature maps to a thermal void')
    return value, {'chiplet': die_id, 'local_point_mm': point_mm,
                   'package_point_mm': [float(gx), float(gy)], 'grid_index_xy': [ix, iy]}


def sky_instance_model(root, cell, instance, temperature_c, output, corners=('tt_025C_1v80', 'tt_100C_1v80')):
    identifier(instance)
    number(temperature_c, 'local temperature_c')
    if cell not in ('buf_8', 'dfxtp_1'):
        raise ValueError('unsupported characterized SKY130 cell')
    root = Path(root)
    a, b = [sky_header(root, corner) for corner in corners]
    # Process labels are explicit, since nominal process numbers are not IDs.
    if corners[0].split('_')[0] != corners[1].split('_')[0] or a['nom_voltage'] != b['nom_voltage']:
        raise ValueError('temperature interpolation requires equal process and voltage')
    low_c, high_c = a['nom_temperature'], b['nom_temperature']
    if not low_c <= temperature_c <= high_c or low_c >= high_c:
        raise ValueError(f'temperature outside characterization interval [{low_c}, {high_c}] C')
    fraction = (temperature_c-low_c)/(high_c-low_c)
    source_paths = [root/f'sky_{cell}_{corner}.json' for corner in corners]
    body = interpolate_cell(*(json.loads(p.read_text()) for p in source_paths), fraction)
    header = copy.deepcopy(a)
    for key in list(header):
        if key.startswith('operating_conditions,'):
            del header[key]
    header['nom_temperature'] = temperature_c
    header['default_operating_conditions'] = 'local_condition'
    header['operating_conditions,local_condition'] = dict(process=1.0, voltage=a['nom_voltage'], temperature=temperature_c)
    name = 'thermal_'+instance
    header['cell,'+name] = body
    Path(output).write_text(f'library("local_{instance}") {{\n'+render_json_liberty(header)+'\n}\n')
    return {'path': str(output), 'cell': name, 'temperature_c': temperature_c,
            'process': corners[0].split('_')[0], 'voltage_v': a['nom_voltage'],
            'bracket_c': [low_c, high_c], 'fraction': fraction,
            'characterization': 'endpoint' if fraction in (0, 1) else 'linear_interpolation_unvalidated',
            'source_files': {p.name: digest(p) for p in source_paths+[root/'sky_common.json']+
                             [root/f'sky_{corner}.json' for corner in corners]}}


def normalize_gf_json(value):
    """Convert GF180's space-delimited groups/numeric strings to typed JSON."""
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            name, _, args = key.partition(' ')
            normalized = name+(','+args.strip() if args.strip() else '')
            if name.startswith('index_') or name == 'values':
                # GF180 represents numeric table rows as strings in a list.
                rows = child if isinstance(child, list) else [child]
                if rows and isinstance(rows[0], str):
                    parsed = [[float(x) for x in row.replace('"', '').split(',')] for row in rows]
                    result[normalized] = parsed[0] if name.startswith('index_') else parsed
                else:
                    result[normalized] = normalize_gf_json(child)
            else:
                result[normalized] = normalize_gf_json(child)
        return result
    if isinstance(value, list):
        return [normalize_gf_json(v) for v in value]
    if isinstance(value, str) and re.fullmatch(r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?', value):
        return float(value)
    return value


def gf_instance_model(root, cell, instance, temperature_c, output):
    identifier(instance)
    number(temperature_c, 'local temperature_c')
    if cell not in ('inv_1', 'dffq_1') or not -40 <= temperature_c <= 125:
        raise ValueError('GF180 model requires inv_1/dffq_1 and -40 <= temperature_c <= 125 at FF 1.98 V')
    root = Path(root)
    corners = ('ff_n40C_1v98', 'ff_125C_1v98')
    paths = [root/f'gf_{cell}_{corner}.json' for corner in corners]
    tables = [next(iter(normalize_gf_json(json.loads(p.read_text())).values())) for p in paths]
    fraction = (temperature_c+40)/165
    body = interpolate_cell(*tables, fraction)
    # Preserve the matching library's original units, scaling factors and LUT
    # templates. Only the library identifier and temperature metadata change.
    source = (root/'gf_core_ff_n40C_1v98.lib').read_text()
    header = source[:re.search(r'\bcell\s*\(', source).start()]
    header = re.sub(r'library\s*\([^)]*\)', f'library("local_{instance}")', header, count=1)
    header = re.sub(r'\b(nom_temperature|temperature)\s*:\s*[-+0-9.eE]+',
                    lambda m: m[1]+f' : {temperature_c:.12g}', header)
    name = 'thermal_'+instance
    Path(output).write_text(header+render_json_liberty({'cell,'+name: body})+'\n}\n')
    return {'path': str(output), 'cell': name, 'temperature_c': temperature_c,
            'process': 'ff', 'voltage_v': 1.98, 'bracket_c': [-40, 125], 'fraction': fraction,
            'characterization': 'endpoint' if fraction in (0, 1) else 'linear_interpolation_unvalidated',
            'source_files': {p.name: digest(p) for p in paths+[root/'gf_core_ff_n40C_1v98.lib']}}


LANE_INSTANCES = {'tx_reg': ('tx', 'dfxtp_1'), 'tx_data': ('tx', 'buf_8'),
                  'tx_clock': ('tx', 'buf_8'), 'rx_clock': ('rx', 'inv_1'), 'rx_reg': ('rx', 'dffq_1')}


def build_temperature_models(case, temperature_c, locations, root, output):
    """Explicit supported profile: SKY FF 1.65 V and GF FF 1.98 V core cells."""
    fields(locations, ('coordinate_unit', 'instances'))
    if locations['coordinate_unit'] != 'mm':
        raise ValueError('instance coordinate_unit must be mm')
    locations = locations['instances']
    if not isinstance(locations, dict) or locations.keys() != LANE_INSTANCES.keys():
        raise ValueError('locations must assign every lane instance exactly once')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    models = {}
    for instance, (die, cell) in LANE_INSTANCES.items():
        value, position = sample_instance_temperature(case, temperature_c, die, locations[instance])
        path = output/(instance+'.lib')
        if die == 'tx':
            model = sky_instance_model(root, cell, instance, value, path, ('ff_n40C_1v65', 'ff_100C_1v65'))
        else:
            model = gf_instance_model(root, cell, instance, value, path)
        model['position'] = position
        models[instance] = model
    return models


def run_coupled_timing(case, temperature_c, output, sta, model_root, locations, period_ns=20.0):
    from .timing import run_timing
    root, output = Path(model_root), Path(output)
    models = build_temperature_models(case, temperature_c, locations, root, output/'temperature_models')
    report = run_timing(case, output/'timing', sta, root/'sky_ff_n40C_1v65.lib',
                        root/'gf_core_ff_n40C_1v98.lib', period_ns=period_ns, instance_models=models)
    report['profile'] = 'SKY130_FF_1.65V_GF180_FF_1.98V_core_harness'
    report['package_resistance_temperature'] = 'fixed_reference_R_no_package_temperature_coefficient'
    report['physical_validation'] = 'not_validated_against_SPICE_holdout_or_measurements'
    (output/'timing/timing.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    return report
