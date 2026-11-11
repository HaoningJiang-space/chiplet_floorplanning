"""Assemble hash-locked public cells without changing their timing tables."""
import argparse
import json
from pathlib import Path

from chiplet_floorplanning.characterization import digest, write_sky_library


SKY_CORNERS = ('tt_025C_1v80', 'tt_100C_1v80', 'ff_n40C_1v65', 'ff_100C_1v65', 'ss_100C_1v60')
GF_CORNERS = ('tt_025C_1v80', 'ff_n40C_1v98', 'ff_125C_1v98', 'ss_n40C_1v62', 'ss_125C_1v62')


def prepare(root):
    root = Path(root)
    lock = json.loads(Path(__file__).with_name('sources.lock.json').read_text())
    records = [r for r in lock['files'] if r['path'].startswith('pdk-v03/')]
    if not records:
        raise ValueError('missing v0.3 source lock')
    for record in records:
        if digest(root/record['path']) != record['sha256']:
            raise ValueError('source hash mismatch: '+record['path'])
    models = root/'pdk-v03'
    generated = []
    for corner in SKY_CORNERS:
        target = models/f'sky_{corner}.lib'
        write_sky_library(models, corner, target)
        generated.append(target)
    header = (models/'gf_io_tt_3v3.lib').read_text().rstrip()
    if not header.endswith('}'):
        raise ValueError('invalid GF180 library header')
    target = models/'gf_io_tt_3v3_assembled.lib'
    target.write_text(header[:-1]+'\n'+(models/'gf_in_c_tt_3v3.lib').read_text()+'\n}\n')
    generated.append(target)
    report = {'status': 'assembled_original_tables', 'inputs': records,
              'outputs': [{'file': p.name, 'sha256': digest(p)} for p in generated],
              'full_PVT': False, 'physical_calibration': 'not_available'}
    (models/'assembly.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('local'))
    print(json.dumps(prepare(parser.parse_args().root), indent=2))
