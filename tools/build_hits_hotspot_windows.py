from pathlib import Path
import shutil, subprocess, json, argparse
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description='Build a local Windows HotSpot exporter using existing SuperLU static libraries.')
parser.add_argument('--hits', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
hits = args.hits.resolve()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)
src = out / 'source'
shutil.copytree(hits / 'third_party/HotSpot', src, ignore=shutil.ignore_patterns('.git'), dirs_exist_ok=True)
p = src / 'temperature_grid.c'
s = p.read_text()
pairs = [('void direct_SLU(grid_model_t *model,', '#include "hotspot_export.h"\n\nvoid direct_SLU(grid_model_t *model,'), ('  P = build_transient_power_vector(model, power);\n\n  if(MAKE_CSVS)', '  P = build_transient_power_vector(model, power);\n  hits_export(model, &A, P);\n\n  if(MAKE_CSVS)'), ('  dp = (double *) Astore->nzval;\n  //copy results', '  dp = (double *) Astore->nzval;\n  hits_reference(dp, dim, info);\n  //copy results')]
for before, after in pairs:
    assert s.count(before) == 1
    s = s.replace(before, after)
p.write_text(s)
shutil.copy2(hits / 'tools/native/hotspot_export.h', src)
names = 'hotspot temperature RCutil package temperature_block temperature_grid flp flp_desc npe shape util wire microchannel materials'.split()
cmd = ['x86_64-w64-mingw32-gcc.exe', '-std=gnu99', '-O3', '-DVERBOSE=1', '-DMATHACCEL=0', '-DDEBUG3D=0', '-DSUPERLU=1', '-I' + str(root / 'local/upstream/superlu/SRC'), '-I' + str(root / 'local/build/superlu/SRC')] + [str(src / (n + '.c')) for n in names] + [str(root / 'local/build/superlu/SRC/libsuperlu.a'), str(root / 'local/build/superlu/CBLAS/libblas.a'), '-lm', '-o', str(out / 'hotspot.exe')]
with (out / 'build.log').open('w') as f:
    result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
(out / 'command.json').write_text(json.dumps({'command': cmd, 'returncode': result.returncode}, indent=2))
print('returncode', result.returncode)
print((out / 'build.log').read_text()[-6000:])
raise SystemExit(result.returncode)
