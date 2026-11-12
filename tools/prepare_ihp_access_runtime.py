"""Local PDK copy with two Tcl path-argument fixes for Windows; no geometry edits."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

PIN='a700e4a04724e0e2f266b3161eb19e0476b747d3'
TARGET='libs.tech/klayout/python/pycell4klayout-api/source/python/cni/dlo.py'
REPLACEMENTS=[
    ('PCellWrapper._tcl.eval(f"source {modulePath}")',
     'PCellWrapper._tcl.call("source", modulePath)'),
    ('PCellWrapper._tcl.eval(f"setCniPythonPath {os.path.normpath(os.path.dirname(__file__))}")',
     'PCellWrapper._tcl.call("setCniPythonPath", os.path.normpath(os.path.dirname(__file__)))'),
]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=Path('local/upstream/OpenIntM4TM2'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    archive=subprocess.check_output(['git','-C',str(args.source),'archive',PIN])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(args.output,filter='data')
    path=args.output/TARGET;before=path.read_bytes();after=before.decode('utf-8')
    for old,new in REPLACEMENTS:
        if after.count(old)!=1:raise ValueError('Unexpected path fix target')
        after=after.replace(old,new)
    path.write_bytes(after.encode('utf-8'))
    receipt=dict(source_commit=PIN,modified_file=TARGET,
                 before_sha256=hashlib.sha256(before).hexdigest(),
                 after_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                 replacements=REPLACEMENTS,scope='Tcl argument quoting only; original upstream untouched')
    (args.output/'windows-path-fix.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':main()
