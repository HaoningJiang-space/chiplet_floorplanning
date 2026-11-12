from pathlib import Path
import sys, json, time, argparse, os, subprocess
parser = argparse.ArgumentParser(description='Solve a generated TAP case with the pinned HiTS native frontend; retain model-transfer diagnostics.')
parser.add_argument('--hits', type=Path, required=True)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--input', type=Path, required=True)
parser.add_argument('--allow-unqualified-native-diagnostic', action='store_true', help='Permit diagnostic solve despite unresolved native physical model; never layout admission')
args = parser.parse_args()
sys.path.insert(0, str(args.hits.resolve()))
from tools.native_io import read_hotspot, CONVENTION
from hits import ThermalOperator, HiTS
import numpy as np
out = args.input.resolve()
if (out / 'fields.bin').exists():
    raise ValueError('Use freshly generated inputs; preserve prior results')
env = os.environ.copy()
env['HITS_HOTSPOT_EXPORT'] = str(out / 'fields.bin')
env['HITS_HOTSPOT_REFERENCE'] = str(out / 'reference.bin')
cmd = [str(args.binary.resolve()), '-c', str(out / 'new_hotspot.config'), '-f', str(out / 'caseL4_ChipLayer.flp'), '-p', str(out / 'case.ptrace'), '-model_type', 'grid', '-detailed_3D', 'on', '-grid_layer_file', str(out / 'caselayers.lcf')]
with (out / 'native7.log').open('w') as log:
    subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
a, b, r, shape = read_hotspot(out / 'fields.bin')
if shape != (64, 64, 8):
    raise ValueError('Expected sourced TAP 64 by 64 grid with six input and two package layers')
print('start', shape, a.shape, a.nnz, flush=True)
if not args.allow_unqualified_native_diagnostic:
    (out/'admission.json').write_text(json.dumps(dict(accepted_for_layout=False, reason='Pinned HotSpot7 detailed3D internal package edge depends on external convection; see tap-native-boundary-audit.md'),indent=2)+'\n')
    raise SystemExit('Native physical boundary admission failed; use the explicit diagnostic flag only for investigation')
q = ThermalOperator(a, b, None, CONVENTION, 'native-layer-row-column-package', r, 'HotSpot', '7.0', 'tap-native-input', ('unknown', 'unknown', 'unknown'))
t, receipt = HiTS().solve_steady(q)
ref = np.fromfile(out / 'reference.bin', dtype=np.float64)
if ref.shape != t.shape or not np.all(np.isfinite(ref)):
    raise ValueError('Invalid native reference')
g = np.asarray(a @ np.ones(len(b)))
source_power = b - 318.15*g
expected_power = json.loads((out/'inputs.json').read_text())['total_power_w']
off = a.copy()
off.setdiag(0)
off.eliminate_zeros()
asymmetry = a-a.T
invariants = dict(source_power_w=float(source_power.sum()), expected_power_w=expected_power,
    boundary_heat_out_w=float(g @ (t-318.15)),
    minimum_boundary_conductance_w_k=float(g.min()),
    maximum_offdiagonal_w_k=float(off.data.max()),
    maximum_asymmetry_w_k=float(abs(asymmetry.data).max()) if asymmetry.nnz else 0,
    minimum_temperature_above_ambient_k=float(t.min()-318.15))
np.save(out / 'hits-temperature.npy', t)
result = {'physical_qualified': False, 'model_transfer_status': 'HotSpot6_to_7_detailed3D_equivalence_not_established', 'invariants': invariants, 'shape': shape, 'nodes': len(b), 'receipt': receipt, 'native_difference_max_k': float(abs(t - ref).max()), 'peak_chip_layer_c': float(t[4 * 64 * 64:5 * 64 * 64].max() - 273.15)}
(out / 'hits-result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2), flush=True)
if not receipt['accepted']:
    raise SystemExit('HiTS original-equation acceptance failed; not thermal infeasibility')
