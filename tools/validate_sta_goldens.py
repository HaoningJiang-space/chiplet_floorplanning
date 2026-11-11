"""Replay three unchanged upstream OpenSTA annotation cases and original goldens."""

import argparse
from chiplet_floorplanning.cli import source_revision
import difflib
import re
import shutil
import subprocess
from pathlib import Path
from validation.sources import verify, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path("local"))
    p.add_argument("--sta", type=Path, default=Path("local/upstream/OpenSTA/app/sta"))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    hashes = verify(args.root, "open-cases/opensta/")
    source = args.root / "open-cases/opensta"
    shutil.copyfile(source / "LICENSE", args.output / "UPSTREAM-LICENSE")
    reports = []
    for i, label in ((1, "sdf"), (3, "liberty_min_max"), (4, "spef")):
        out = args.output / label
        out.mkdir()
        for f in (source / "examples").iterdir():
            shutil.copyfile(f, out / f.name)
        run = subprocess.run(
            [str(args.sta.resolve()), "-no_init", "-exit", f"example{i}.tcl"],
            cwd=out,
            capture_output=True,
            text=True,
            timeout=120,
        )
        log = run.stdout + run.stderr
        (out / "sta.log").write_text(log)
        expected = (source / "test" / f"example{i}.ok").read_text().strip()
        index = log.find("Startpoint:")
        actual = log[index:].strip() if index >= 0 else ""
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile="upstream",
                tofile="actual",
            )
        )
        (out / "difference.txt").write_text(diff)
        passed = (
            run.returncode == 0
            and not re.search(r"(?im)^(Error|Warning):", log)
            and actual == expected
        )
        reports.append(
            dict(
                name=label,
                passed=passed,
                paths=actual.count("Startpoint:"),
                comparison="exact printed report match",
            )
        )
    report = dict(
        source_revision=source_revision(),
        passed=all(r["passed"] for r in reports),
        cases=reports,
        source_hashes=hashes,
        independent_design_count=1,
        scope="STA engine regression only; upstream example library is not a PDK",
        physical_calibration=False,
    )
    write_json(args.output / "report.json", report)
    print(reports)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
