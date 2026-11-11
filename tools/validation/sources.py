"""Hash checks shared by external validation runners."""

import hashlib
import json
from pathlib import Path

LOCK = Path(__file__).resolve().parents[1] / "sources.lock.json"


def verify(root, prefix):
    records = [
        r for r in json.loads(LOCK.read_text())["files"] if r["path"].startswith(prefix)
    ]
    if not records:
        raise ValueError(f"no locked sources for {prefix}")
    for record in records:
        path = root / record["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"source hash mismatch: {path}")
    return {r["path"]: r["sha256"] for r in records}


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
