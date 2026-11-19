"""Capture verified sender/receiver payload counts from the official NPB 3.4.3 MPI suite."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np

SOURCE_SHA = "a97c03d7e87ab826fba79c754415a13632c5273877abad270c85201db0f86aeb"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive.resolve()
    assert digest(archive) == SOURCE_SHA
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    subprocess.run(["tar", "-xzf", archive, "NPB3.4.3/NPB3.4-MPI"], cwd=out, check=True)
    root = out / "NPB3.4.3/NPB3.4-MPI"
    shutil.copyfile(root / "config/make.def.template", root / "config/make.def")
    (root / "bin").mkdir(exist_ok=True)
    with (out / "build.log").open("w") as log:
        for target in ("is", "dt"):
            subprocess.run(
                ["make", target, "CLASS=S"],
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
    c = Path(__file__).with_suffix(".c").resolve()
    lib = out / "libnpb_payload.so"
    subprocess.run(
        [
            "mpicc",
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-fPIC",
            "-shared",
            c,
            "-o",
            lib,
        ],
        check=True,
    )
    records = {}
    for name in ("IS", "BH", "WH", "SH"):
        d = out / name
        d.mkdir()
        program = [root / "bin/is.S.x"] if name == "IS" else [root / "bin/dt.S.x", name]
        with (d / "benchmark.log").open("w") as log:
            subprocess.run(
                [
                    "mpirun",
                    "--bind-to",
                    "none",
                    "-n",
                    "16",
                    "env",
                    "LD_PRELOAD=" + str(lib),
                    "NPB_TRACE_DIR=" + str(d),
                    *program,
                ],
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=150,
            )
        log = (d / "benchmark.log").read_text()
        assert re.search(r"Verification\s*=\s*SUCCESSFUL", log), name
        rows = [(d / f"rank-{i}.txt").read_text().splitlines() for i in range(16)]
        assert all(int(row[0]) == (11 if name == "IS" else 0) for row in rows)
        ledgers = np.array(
            [[list(map(int, entry.split())) for entry in row[1:]] for row in rows]
        )
        sent, received = ledgers[:, :, 0], ledgers[:, :, 1]
        assert (
            sent.shape == (16, 16)
            and np.array_equal(sent, received.T)
            and sent.sum() > 0
        )
        if name == "IS":
            assert sent.sum() == 10 * (2**16) * 4
        records[name] = dict(
            verification="SUCCESSFUL",
            payload_bytes=sent.tolist(),
            total_bytes=int(sent.sum()),
            self_bytes=int(np.trace(sent)),
            benchmark_log_sha256=digest(d / "benchmark.log"),
        )
    record = dict(
        source_sha256=SOURCE_SHA,
        source_url="https://www.nas.nasa.gov/assets/npb/NPB3.4.3.tar.gz",
        capture_sha256={s.name: digest(s) for s in (c, Path(__file__))},
        mpi_version=subprocess.check_output(
            ["mpirun", "--version"], text=True
        ).splitlines()[0],
        ranks=16,
        benchmark_class="S",
        workloads=records,
    )
    (out / "payload.json").write_text(json.dumps(record, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
