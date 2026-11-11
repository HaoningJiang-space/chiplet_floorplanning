"""Install hash-locked MSYS2 ngspice runtime files into a local folder only."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
from urllib.request import urlopen

import zstandard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('local/ngspice-42-msys2'))
    args = parser.parse_args()
    root = args.root.resolve()
    lock_path = Path(__file__).with_name('ngspice-windows.lock.json')
    lock = json.loads(lock_path.read_text())
    manifest = {}
    for package in lock['packages']:
        archive = root / 'packages' / package['url'].rsplit('/', 1)[1]
        if not archive.exists():
            with urlopen(package['url'], timeout=60) as stream:
                payload = stream.read()
            if hashlib.sha256(payload).hexdigest() != package['sha256']:
                raise ValueError('download hash mismatch: ' + package['name'])
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(payload)
        payload = archive.read_bytes()
        if hashlib.sha256(payload).hexdigest() != package['sha256']:
            raise ValueError('archive hash mismatch: ' + package['name'])
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(payload)) as stream:
            with tarfile.open(fileobj=stream, mode='r|') as tar:
                for member in tar:
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or '..' in path.parts:
                        raise ValueError('unsafe package path')
                    if not path.parts or path.parts[0] != 'ucrt64' or member.isdir():
                        continue
                    if not path.as_posix().startswith(('ucrt64/bin/', 'ucrt64/lib/ngspice/',
                                                       'ucrt64/share/ngspice/', 'ucrt64/share/licenses/')):
                        continue  # No headers, package hooks or timezone-link tree is needed.
                    if not member.isfile():
                        raise ValueError('nonregular runtime member: ' + member.name)
                    target = root / path
                    if target.is_symlink() or any(p.is_symlink() for p in target.parents):
                        raise ValueError('refusing runtime symlink')
                    content = tar.extractfile(member).read()
                    if target.exists() and target.read_bytes() != content:
                        raise ValueError('existing runtime differs: ' + str(target))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                    manifest[path.as_posix()] = hashlib.sha256(content).hexdigest()
        print('Verified ' + package['name'], flush=True)
    executable = root / lock['executable']
    version = subprocess.check_output([str(executable), '-n', '--version'], text=True)
    if lock['expected_version'] not in version:
        raise ValueError('unexpected ngspice version')
    receipt = dict(lock_sha256=hashlib.sha256(lock_path.read_bytes()).hexdigest(),
                   packages=lock['packages'], files_sha256=manifest,
                   executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                   version=version, scope='Local portable runtime; no system installation or package scripts executed')
    (root / 'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(version.strip())


if __name__ == '__main__':
    main()
