"""Strict import of pinned rectangular, two-pin ATPlace benchmark inputs.

No optimizer, thermal solver, bump assignment or feasibility claim is involved.
Decimal strings preserve the source's percentage offsets without rounding.
"""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess

PIN = 'fe3dbfdaf78dc0ddeac3a2cfc3a85ff0971f88df'
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'


def lines(text):
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]


def headers(records, keys):
    values = {}
    while records and ':' in records[0] and records[0].split(':')[0].strip() in keys:
        key, value = records.pop(0).split(':')
        key = key.strip()
        if key in values or not re.fullmatch(r'\d+', value.strip()):
            raise ValueError('duplicate or malformed header')
        values[key] = int(value)
    if set(values) != set(keys):
        raise ValueError('missing header')
    return values


def rotate_offset(x_um, y_um, degrees):
    """Exact counterclockwise rotation about chiplet centre, in micrometres."""
    x, y = Decimal(x_um), Decimal(y_um)
    if degrees not in (0, 90, 180, 270):
        raise ValueError('only quarter turns supported')
    for _ in range(degrees//90):
        x, y = -y, x
    return str(x), str(y)


def parse_case(name, blocks, power, nets):
    records = lines(blocks)
    h = headers(records, ('NumSoftRectangularBlocks', 'NumHardRectilinearBlocks',
                          'NumTerminals', 'InterposerWidth', 'InterposerHeight'))
    if h['NumSoftRectangularBlocks'] or h['NumTerminals'] or min(h['InterposerWidth'], h['InterposerHeight']) <= 0:
        raise ValueError('only positive rectangular domains without soft blocks or terminals supported')
    chips = {}
    for record in records:
        match = re.fullmatch(r'(\w+)\s+hardrectilinear\s+4\s+(.+)', record)
        if not match or match[1] in chips:
            raise ValueError('malformed or duplicated block')
        coords = re.findall(r'\(\s*(\d+)\s*,\s*(\d+)\s*\)', match[2])
        residue = re.sub(r'\(\s*\d+\s*,\s*\d+\s*\)', '', match[2]).strip()
        if len(coords) != 4 or residue:
            raise ValueError('invalid rectangle coordinates')
        points = [(int(x), int(y)) for x, y in coords]
        w, ht = max(x for x, y in points), max(y for x, y in points)
        if w <= 0 or ht <= 0 or set(points) != {(0, 0), (0, ht), (w, ht), (w, 0)}:
            raise ValueError('block must be a positive origin-based rectangle')
        chips[match[1]] = dict(name=match[1], width_um=w, height_um=ht)
    if len(chips) != h['NumHardRectilinearBlocks'] or not chips:
        raise ValueError('block count mismatch')
    powered = set()
    for record in lines(power):
        fields = record.split()
        if len(fields) != 2 or fields[0] not in chips or fields[0] in powered:
            raise ValueError('unknown, duplicated or malformed power record')
        value = Decimal(fields[1])
        if not value.is_finite() or value < 0:
            raise ValueError('invalid power')
        powered.add(fields[0])
        chips[fields[0]]['power_w_decimal'] = str(value)
    if powered != set(chips):
        raise ValueError('missing power record')
    records = lines(nets)
    nh = headers(records, ('NumNets', 'NumPins'))
    connections = []
    cursor = 0
    while cursor < len(records):
        if records[cursor] != 'NetDegree : 2' or cursor+2 >= len(records):
            raise ValueError('expected complete two-pin net')
        pins = []
        for record in records[cursor+1:cursor+3]:
            match = re.fullmatch(r'(\w+)\s+(\w+)\s*:\s*%('+NUMBER+r')\s+%('+NUMBER+r')', record)
            if not match or match[1] not in chips:
                raise ValueError('unknown chiplet or malformed percentage pin')
            px, py = Decimal(match[3]), Decimal(match[4])
            if abs(px) > 50 or abs(py) > 50:
                raise ValueError('pin outside declared rectangle')
            chip = chips[match[1]]
            pins.append(dict(chiplet=match[1], direction=match[2],
                             offset_x_percent=str(px), offset_y_percent=str(py),
                             offset_x_um_decimal=str(px*chip['width_um']/100),
                             offset_y_um_decimal=str(py*chip['height_um']/100)))
        connections.append(dict(id=len(connections), pins=pins))
        cursor += 3
    if len(connections) != nh['NumNets'] or 2*len(connections) != nh['NumPins']:
        raise ValueError('net or pin count mismatch')
    return dict(name=name, interposer_width_um=h['InterposerWidth'],
                interposer_height_um=h['InterposerHeight'], chiplets=list(chips.values()), nets=connections,
                scope='source geometry/power/pins only; no bump, routing, thermal or timing qualification',
                power_provenance='published benchmark input, not verified measurement',
                placement_grid_um=None, gap_um=None, bump_footprints=None,
                package_model=None, timing_constraints=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for i in range(1, 11):
        name = f'Case{i}'
        raw = {ext: subprocess.check_output(['git', '-C', str(args.source), 'show',
                    f'{PIN}:cases/{name}/{name}.{ext}']) for ext in ('blocks', 'power', 'nets')}
        case = parse_case(name, **{ext: data.decode('utf-8') for ext, data in raw.items()})
        case['source_commit'] = PIN
        case['source_sha256'] = {ext: hashlib.sha256(data).hexdigest() for ext, data in raw.items()}
        encoded = (json.dumps(case, indent=2)+'\n').encode()
        (args.output/f'{name}.json').write_bytes(encoded)
        summaries.append(dict(case=name, chiplets=len(case['chiplets']), nets=len(case['nets']),
                              pins=2*len(case['nets']), source_sha256=case['source_sha256'],
                              imported_sha256=hashlib.sha256(encoded).hexdigest(),
                              status='source_records_validated_not_layout_feasibility'))
    summary = dict(source_commit=PIN, cases=summaries,
                   importer_sha256=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest())
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps([{k: r[k] for k in ('case', 'chiplets', 'nets', 'status')} for r in summaries]))


if __name__ == '__main__':
    main()
