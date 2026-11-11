"""Public measurement source verification; no raw measurements in Git."""

import hashlib
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen

LOCK = Path(__file__).resolve().parents[1] / 'measured-sources.lock.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(root):
    lock = json.loads(LOCK.read_text())
    for r in lock['files']:
        p = Path(root) / r['path']
        if digest(p) != r['sha256']:
            raise ValueError(f'measured source hash mismatch: {p}')
    return lock


def bootstrap(root):
    root = Path(root).resolve()
    lock = json.loads(LOCK.read_text())
    for r in lock['files']:
        if 'url' not in r:
            continue
        p = root / r['path']
        if p.exists():
            if digest(p) != r['sha256']:
                raise ValueError(f'existing source mismatch: {p}')
            continue
        with urlopen(r['url'], timeout=120) as stream:
            data = stream.read()
        if hashlib.sha256(data).hexdigest() != r['sha256']:
            raise ValueError('download hash mismatch')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    with tarfile.open(root / 'sources/thermal-release.tar.gz') as archive:
        for m in archive:
            dest = (root / 'thermal-original' / m.name).resolve()
            if not dest.is_relative_to(root / 'thermal-original') or not (m.isfile() or m.isdir()):
                raise ValueError('unsafe thermal archive member')
            if m.isfile():
                data = archive.extractfile(m).read()
                if dest.exists() and dest.read_bytes() != data:
                    raise ValueError('existing extracted measurement differs')
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
    return verify(root)
