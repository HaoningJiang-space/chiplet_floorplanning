"""Extract pinned published case inputs; do not execute upstream code."""
import argparse
import configparser
import hashlib
import json
import math
from pathlib import Path
import subprocess

COMMIT = '3a3f4e5a4d019b2d9cda1f72d8d1755238845dbb'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = []
    for name in ('ascend910', 'micro150', 'multigpu'):
        filename = f'configs/sys_{name}.cfg'
        raw = subprocess.check_output(['git', 'show', f'{COMMIT}:{filename}'], cwd=args.repository)
        config = configparser.ConfigParser()
        config.read_string(raw.decode('utf-8'))
        section = config['chiplets']
        count = section.getint('chiplet_count')
        values = {k: [float(v) for v in section[k].split(',')] for k in ('widths', 'heights', 'powers')}
        matrix = [[float(v) for v in row.split(',')] for row in section['connections'].split(';')]
        if any(len(v) != count or any(not math.isfinite(x) or x <= 0 for x in v) for v in values.values()):
            raise ValueError('invalid dimensions or power')
        if len(matrix) != count or any(len(row) != count or any(not math.isfinite(x) or x < 0 for x in row) for row in matrix):
            raise ValueError('invalid connectivity matrix')
        if any(matrix[i][i] != 0 for i in range(count)):
            raise ValueError('unexpected self demand')
        cases.append(dict(name=name, source_path=filename,
            source_url=f'https://github.com/bu-icsg/TAP-2.5D/blob/{COMMIT}/{filename}',
            source_bytes_sha256=hashlib.sha256(raw).hexdigest(),
            classification='published_case_study_input_not_independent_measurement',
            chiplet_count=count, widths_mm=values['widths'], heights_mm=values['heights'],
            powers_w=values['powers'], total_power_w=sum(values['powers']),
            interposer_side_mm=config['interposer'].getfloat('intp_size'),
            upstream_placement_granularity_mm=config['general'].getfloat('placer_granularity'),
            link_type=config['interposer']['link_type'],
            connection_matrix_source_values=matrix,
            connection_units='unresolved_bandwidth_to_wire_conversion',
            qualified_physical_benchmark=False))
    result = dict(upstream_commit=COMMIT, imported_cases=cases,
        status='source_ledger_only_not_an_executable_floorplanning_benchmark',
        missing=['explicit PHY/bump map', 'bandwidth-to-wire convention',
                 'track-layer capacity rules', 'frozen independent placement domain',
                 'package boundary transfer validation'])
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({c['name']: dict(chiplets=c['chiplet_count'], power_w=c['total_power_w']) for c in cases}))


if __name__ == '__main__':
    main()
