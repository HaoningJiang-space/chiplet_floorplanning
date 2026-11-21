"""Frozen inputs, admission rules and verified layout metrics for the successor placement comparison."""
from hashlib import sha256
import json
from operator import itemgetter
from pathlib import Path

import numpy as np

from chiplet_floorplanning.placement import Layout, Problem
from continuous_metrics import escape_util, point, verified
from import_atplace_cases import parse_case


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence"


def load_case(name, source):
    """Return the problem, starting layout, per-net reach (mm), wire cap (m) and frozen input bytes."""
    frozen = json.loads((EVIDENCE / 'successor-freeze.json').read_bytes())
    fixtures = {'Stagger12P': 'successor-distinct-pins.json', 'DualStar14': 'continuous-hotspot-holdout.json'}
    if name == 'Stagger12' or name in fixtures:
        rec = frozen['holdout'] if name == 'Stagger12' else json.loads((EVIDENCE / fixtures[name]).read_bytes())
        raw = {}
        for ext, digest in rec['files_sha256'].items():
            path = ROOT / 'examples' / name / f'{name}.{ext}'
            contents = path.read_bytes().replace(b'\r\n', b'\n')
            assert sha256(contents).hexdigest() == digest
            raw[ext] = contents.decode()
        data = parse_case(name, raw['blocks'], raw['power'], raw['nets'])
        data['power_provenance'] = 'declared synthetic held-out workload'
        encoded = json.dumps(data, separators=(',', ':')).encode()
        centres, angles = rec['start_um'], rec['angles']
    else:
        geom = (EVIDENCE / 'continuous-reach-geometry.json').read_bytes()
        # The historical JSON may have been checked out with Windows CRLF.
        lf = geom.replace(b'\r\n', b'\n')
        assert frozen['legacy_geometry_sha256'] in {
            sha256(s).hexdigest() for s in (lf, lf.replace(b'\n',b'\r\n'))}
        rec = json.loads(geom)['cases'][name]
        encoded = (source / f'{name}.json').read_bytes()
        assert sha256(encoded).hexdigest() == rec['source_sha256']
        data = json.loads(encoded)
        centres, angles = rec['start']['centre_um'], rec['start']['rotation_deg']
    start = Layout(np.array(centres, dtype=float), np.array(angles, dtype=int))
    return Problem.from_imported(data), start, np.array(rec['reach_mm']), rec['cap_m'], encoded


def audit(p, pose, reach, cap):
    """Admit a layout only if geometry, pin reach, total length and track demand pass."""
    row = point(p, pose, reach, cap)
    row['bin_escape_utilization'] = escape_util(p, pose)
    row['admitted'] = bool(row['feasible'] and row['bin_escape_utilization'] <= 1.)
    return row


def measure(p, pose, row):
    summary, peaks = verified(p, pose)
    return dict(row, peak_c=summary['peak_power_layer_c'], die_peaks_c=peaks.tolist(),
                balance_w=summary['energy_balance_error_w'])


def shared_repair(p, pose, cell, reach, cap):
    original = audit(p, pose, reach, cap)
    if original['admitted']:
        return pose, original, 'raw'
    fixed = cell.toward(pose.centre_um)
    if fixed is not None and audit(p, fixed, reach, cap)['admitted']:
        return fixed, original, 'projected'
    return None, original, 'rejected'


def coolest_verified(rows):
    """Choose the lowest verified peak, breaking ties by total pin length."""
    return min(rows, key=itemgetter('peak_c', 'wire_m'))


def result(rows, base, checks):
    eligible = [row for row in rows if row['admitted']]
    best = coolest_verified(eligible)
    reverse = min(row['wire_m'] for row in eligible if row['peak_c'] <= base['peak_c']+1e-7)
    return dict(verified=rows, peak_c=best['peak_c'], wire_m=best['wire_m'],
                cooling_k=base['peak_c']-best['peak_c'], reverse_m=reverse, new_board_checks=checks)
