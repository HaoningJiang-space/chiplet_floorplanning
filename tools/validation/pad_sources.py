"""Optional hash-locked pad SPICE sources, kept outside the repository."""

import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
from urllib.request import urlopen

LOCK = Path(__file__).resolve().parents[1] / "spice-sources.lock.json"
MATCHED_LIBERTY = "sky130A/libs.ref/sky130_fd_io/lib/sky130_ef_io__gpiov2_pad_tt_tt_025C_1v80_3v30.lib"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def selected_member(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe archive path")
    return bool(path.parts and path.parts[0] == "sky130A") and (
        "spice" in path.parts
        or "ngspice" in path.parts
        or path.name in {"SOURCES", "LICENSE", "COPYING", "nodeinfo.json"}
        or path.as_posix() == MATCHED_LIBERTY
    )


def checked_write(path, data):
    if path.is_symlink():
        raise ValueError(f"refusing source symlink: {path}")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"existing source differs: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def prepare(root, download=False):
    """Verify every consumed file against raw/archive hashes on every invocation."""
    import zstandard

    root = Path(root).resolve()
    lock = json.loads(LOCK.read_text())
    manifest = {}
    for record in lock["files"] + lock["archives"]:
        path = root / record["path"]
        if not path.exists():
            if not download:
                raise ValueError(f"missing {path}; run tools/bootstrap_pad_spice.py")
            for attempt in range(3):
                try:
                    with urlopen(record["url"], timeout=30) as stream:
                        data = stream.read()
                    break
                except OSError:
                    if attempt == 2:
                        raise
            if digest(data) != record["sha256"]:
                raise ValueError(f"download hash mismatch: {path}")
            checked_write(path, data)
        data = path.read_bytes()
        if digest(data) != record["sha256"]:
            raise ValueError(f"source hash mismatch: {path}")
        manifest[record["path"]] = record["sha256"]
        if record in lock["archives"]:
            with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)) as stream:
                with tarfile.open(fileobj=stream, mode="r|") as archive:
                    for member in archive:
                        if not selected_member(member.name) or member.isdir():
                            continue
                        if not member.isfile():
                            raise ValueError("selected archive member is not regular")
                        payload = archive.extractfile(member).read()
                        checked_write(root / member.name, payload)
                        manifest[member.name] = digest(payload)
    # Run the pinned upstream syntax filter without editing the source topology.
    run = subprocess.run(
        [
            sys.executable,
            str(root / "gf180/convert_io_cdl.py"),
            str(root / "gf180/bi_t.cdl"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    checked_write(root / "gf180/bi_t.spice", run.stdout.encode())
    manifest["gf180/bi_t.spice"] = digest(run.stdout.encode())
    return {"lock_sha256": digest(LOCK.read_bytes()), "files": manifest}
