"""Source-pinned necessary attachment-capacity check, not a new TAP process."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys


PINS = {
    'ADK-Tools': '6b6ffcfdfb0deb9f5e0a2259b7193d128c59d2ea',
    'OpenIntM4TM2': 'a700e4a04724e0e2f266b3161eb19e0476b747d3',
    'IHP-Open-ADK': '093ae2e75fbc0b1eb3838a426cc1a59d37240aa0',
    'IHP-Interconnect-IntM4TM2': '6a519e962f7459843a31944e5a86cc1d4ff1cb59',
}


def clique_side(pitch_nm, separation_nm):
    """Largest square block whose site pairs are all strictly too close."""
    if type(pitch_nm) is not int or type(separation_nm) is not int or min(pitch_nm, separation_nm) <= 0:
        raise ValueError('Positive integer nanometres required')
    k = 1
    while 2 * (k * pitch_nm) ** 2 < separation_nm ** 2:
        k += 1
    return k


def strip_bound(nx, ny, k):
    # Partition, not area-density approximation. Cross-block constraints are
    # ignored, which can only make this necessary upper bound more generous.
    return ((nx + k - 1) // k) * ((ny + k - 1) // k)


def capacity_bound(chip, separation_nm):
    w, h, r = (chip[key] for key in ('core_width_um', 'core_height_um', 'bump_ring_um'))
    if r % 45:
        raise ValueError('Expected frozen TAP 45 um lattice')
    k = clique_side(45000, separation_nm)
    strips = [(w+r, r), (r, h+r), (r, h+r), (w+r, r)]
    return dict(block_side_sites=k, site_count=sum((a//45)*(b//45) for a,b in strips),
                populated_sites_upper_bound=sum(strip_bound(a//45, b//45, k) for a,b in strips))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, default=Path('local/upstream'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--local-output', type=Path, required=True)
    args = parser.parse_args()
    files = {}
    def read(repo, relative):
        # Hash the committed source bytes, not Windows checkout CRLF conversion.
        data = subprocess.check_output(['git','-C',str(args.upstream/repo),'show',f'HEAD:{relative}'])
        files[f'{repo}/{relative}'] = hashlib.sha256(data).hexdigest()
        return json.loads(data)
    for repo, expected in PINS.items():
        actual = subprocess.check_output(['git','-C',str(args.upstream/repo),'rev-parse','HEAD'], text=True).strip()
        if actual != expected:
            raise ValueError(f'Unreviewed source revision: {repo} {actual}')
        if subprocess.check_output(['git','-C',str(args.upstream/repo),'status','--porcelain'], text=True).strip():
            raise ValueError(f'Dirty source checkout: {repo}')
    for repo, subpath in [('OpenIntM4TM2','OpenIntM4TM2'),('IHP-Open-ADK','adk'),('IHP-Interconnect-IntM4TM2','IHP-Interconnect-IntM4TM2')]:
        line = subprocess.check_output(['git','-C',str(args.upstream/'ADK-Tools'),'ls-tree','HEAD',f'tools/{subpath}'], text=True)
        if line.split()[2] != PINS[repo]:
            raise ValueError('ADK source bundle gitlink mismatch')
    registry = read('IHP-Interconnect-IntM4TM2','manifest/interconnect_methods.json')
    technology = read('OpenIntM4TM2','libs.tech/adk/technology.json')
    descriptor_path = technology['routing']['variants']['base']['path']
    descriptor = read('OpenIntM4TM2', descriptor_path)
    if files[f'OpenIntM4TM2/{descriptor_path}'] != technology['routing']['variants']['base']['sha256']:
        raise ValueError('Routing descriptor digest mismatch')
    debt = read('ADK-Tools','examples/two_die_interposer/carrier_drc_baseline.json')
    fixture_relative = 'examples/two_die_interposer/'
    for relative in ['outputs/two_die_interposer.chiplet', 'chiplets/metal_test_chiplet.pins.json']:
        data = subprocess.check_output(['git','-C',str(args.upstream/'ADK-Tools'),'show',f'HEAD:{fixture_relative}{relative}'])
        files[f'ADK-Tools/{fixture_relative}{relative}'] = hashlib.sha256(data).hexdigest()
    pillars = read('ADK-Tools',fixture_relative+'outputs/layout/two_die_interposer_interposer.pillars.json')
    args.local_output.mkdir(parents=True, exist_ok=False)
    fixture = args.upstream/'ADK-Tools'/fixture_relative
    checker = args.upstream/'IHP-Open-ADK/checks/pads_vs_pillars.py'
    command = [sys.executable,str(checker),'--chiplet',str(fixture/'outputs/two_die_interposer.chiplet'),
               '--pins',f'U1={fixture / "chiplets/metal_test_chiplet.pins.json"}',
               '--pins',f'U2={fixture / "chiplets/metal_test_chiplet.pins.json"}','--strict']
    alignment = {}
    for name, expected_exit in [('source',0),('displaced',1)]:
        manifest_path = fixture/'outputs/layout/two_die_interposer_interposer.pillars.json'
        if name == 'displaced':
            # First named pillar is not auto-resolved. Move it well beyond tolerance.
            if pillars['pillars'][0]['moved_by_auto_resolve']:
                raise ValueError('Unexpected negative-control source pillar')
            pillars['pillars'][0]['x_um'] += 100
            manifest_path = args.local_output/'displaced-pillars.json'
            manifest_path.write_text(json.dumps(pillars), encoding='utf-8')
        report_path = args.local_output/f'{name}-alignment.json'
        process = subprocess.run(command+['--pillars',str(manifest_path),'--json',str(report_path)],
                                 capture_output=True, text=True, encoding='utf-8')
        (args.local_output/f'{name}.log').write_text(process.stdout+process.stderr, encoding='utf-8')
        if process.returncode != expected_exit:
            raise ValueError(f'Unexpected {name} alignment result: {process.returncode}')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        alignment[name] = dict(exit_code=process.returncode, summary=report['summary'],
                               devices=report['devices'], findings=report['findings'],
                               warnings=report['warnings'],
                               report_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest())
    geometry_path = Path('docs/evidence/tap-geometry-domains.json')
    geometry_bytes = geometry_path.read_bytes()
    cases = json.loads(geometry_bytes)['cases']
    records = []
    for name in registry['default_connection_library']:
        method = registry['methods'][name]
        # Allow the source checker's 10 nm polygon tolerance conservatively.
        opening = Decimal(str(method['fab_params']['passiv_opening_um']))
        spacing = Decimal(str(method['pitch_rules']['IXN_spacing']))
        separation_nm = int((opening + spacing)*1000) - 10
        chips = []
        for case in cases:
            domain = case['domain']; demands = domain['connection_wire_demands']
            for i, chip in enumerate(domain['chiplets']):
                demand = sum(demands[i]) + sum(row[i] for row in demands)
                bound = capacity_bound(chip, separation_nm)
                chips.append(dict(case=domain['name'], chip_id=i, incident_wire_demand=demand,
                                  **bound, necessary_capacity_passed=demand <= bound['populated_sites_upper_bound']))
        records.append(dict(method=name, vendor=method['vendor'], opening_um=float(opening),
                            spacing_um=float(spacing), conservative_min_separation_nm=separation_nm,
                            chips=chips))
    output = dict(status='conditional_attachment_capacity_audit', source_commits=PINS,
                  source_sha256=files, source_hash_convention='committed Git blob bytes',
                  geometry_sha256=hashlib.sha256(geometry_bytes).hexdigest(),
                  routing_layers=descriptor['routing_layers'], methods=records,
                  reference_carrier_known_debt=debt['expected'],
                  local_pad_alignment=alignment,
                  scope='Only subsets of existing 45 um TAP ring sites, one distinct bump per incident conductor; rigid rotations/translations preserve bound.',
                  excluded='No new bump coordinates, ring resizing, multiplexing, demo VendorX method, physical TAP infeasibility or complete manufacturing qualification.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(output, f, indent=2); f.write('\n')
    for method in records:
        print(method['method'], sum(not c['necessary_capacity_passed'] for c in method['chips']), 'of', len(method['chips']), 'chiplets fail necessary capacity')


if __name__ == '__main__':
    main()
