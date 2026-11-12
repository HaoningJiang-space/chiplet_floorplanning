from pathlib import Path
import sys, shutil, subprocess, os, json, argparse
parser = argparse.ArgumentParser(description='Check local native HotSpot equation transfer to HiTS; no physical calibration claim.')
parser.add_argument('--hits', type=Path, required=True)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
hits = args.hits.resolve()
sys.path.insert(0, str(hits))
from tools.native_io import read_hotspot, CONVENTION
from hits import ThermalOperator, HiTS
import numpy as np
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
src = hits / 'third_party/HotSpot/examples/example1'
for p in src.iterdir():
    if p.is_file():
        shutil.copy2(p, out / p.name)
env = os.environ.copy()
env['HITS_HOTSPOT_EXPORT'] = str(out / 'fields.bin')
env['HITS_HOTSPOT_REFERENCE'] = str(out / 'reference.bin')
cmd = [str(args.binary.resolve()), '-c', 'example.config', '-f', 'ev6.flp', '-p', 'gcc.ptrace', '-materials_file', 'example.materials', '-model_type', 'grid', '-grid_rows', '16', '-grid_cols', '16']
with (out / 'native.log').open('w') as f:
    subprocess.run(cmd, cwd=out, env=env, stdout=f, stderr=subprocess.STDOUT, check=True)
a, b, regions, shape = read_hotspot(out / 'fields.bin')
q = ThermalOperator(a, b, None, CONVENTION, 'native-layer-row-column-package', regions, 'HotSpot', '7.0', 'native-smoke', ('unknown', 'unknown', 'unknown'))
t, receipt = HiTS().solve_steady(q)
ref = np.fromfile(out / 'reference.bin', dtype=np.float64)
if ref.shape != t.shape:
    raise ValueError('Native temperature dimensions differ')
result = {'shape': shape, 'nodes': len(b), 'max_absolute_temperature_difference_k': float(np.max(np.abs(t - ref))), 'temperature_range_k': [float(t.min()), float(t.max())], 'receipt': receipt, 'scope': 'local Windows native interface smoke only; not TAP calibration or performance qualification'}
(out / 'result.json').write_text(json.dumps(result, indent=2, default=lambda x: vars(x)))
print((out / 'result.json').read_text())
if not receipt['accepted'] or not np.all(np.isfinite(ref)) or result['max_absolute_temperature_difference_k'] > 0.0001:
    raise SystemExit('Native equation transfer check failed')
