"""Command-line validation and reproducible evaluation artifacts."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np
import scipy

from . import __version__
from .interconnect import estimate_links
from .model import load_case
from .power import rasterize
from .thermal import solve_steady


def source_revision():
    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        return {"commit": None, "dirty": None}
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)
        return {"commit": sha, "dirty": bool(status)}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def evaluate(case, output):
    output = Path(output)
    if output.exists():
        raise ValueError(f"output already exists; choose a new directory: {output}")
    power, blocks = rasterize(case)
    temperature, thermal = solve_steady(case, power)
    links = estimate_links(case)
    input_w = sum(block["input_w"] for block in blocks)
    canonical = json.dumps(case.input_data, indent=2, sort_keys=True, allow_nan=False) + "\n"
    report = {
        "schema_version": 1,
        "case": case.name,
        "scope": "fixed_layout_assumption_driven_reference",
        "validation": {"geometry": "passed", "power_conservation": "passed",
                       "thermal_residual_and_energy_balance": "passed",
                       "thermal_external_validation": "not_run",
                       "cross_die_setup_hold": "not_implemented"},
        "power": {"input_w": input_w, "mapped_w": float(power.sum()),
                  "error_w": float(power.sum()) - input_w, "blocks": blocks},
        "thermal": thermal,
        "links": links,
        "timing": {"status": "not_implemented", "setup_slack_ns": None, "hold_slack_ns": None},
        "provenance": {"input_snapshot_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
                       "tool_version": __version__, "source": source_revision(),
                       "python": platform.python_version(), "numpy": np.__version__,
                       "scipy": scipy.__version__, "timestamp_utc": datetime.now(timezone.utc).isoformat()},
    }
    encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
    output.mkdir(parents=True, exist_ok=False)
    (output / "input.json").write_text(canonical, encoding="utf-8")
    dx, dy = case.package.width / case.nx, case.package.height / case.ny
    with (output / "grid.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["ix", "iy", "x_center_mm", "y_center_mm", "power_w", "power_density_w_mm2", "temperature_c"])
        for y in range(case.ny):
            for x in range(case.nx):
                writer.writerow([x, y, (x + 0.5) * dx, (y + 0.5) * dy, power[y, x],
                                 power[y, x] / (dx * dy), temperature[y, x]])
    # Written last: its presence indicates completion of the other artifacts.
    (output / "report.json").write_text(encoded, encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fixed-layout chiplet evaluation (uncalibrated reference model)")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate geometry, units, sources, and connectivity")
    validate.add_argument("case", type=Path)
    run = subparsers.add_parser("evaluate", help="map power and solve the uniform-slab reference")
    run.add_argument("case", type=Path)
    run.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        case = load_case(args.case)
        if args.command == "validate":
            print(f"VALID {case.name}: {len(case.dies)} chiplets, {len(case.links)} links")
        else:
            report = evaluate(case, args.output)
            print(f"{case.name}: power={report['power']['mapped_w']:.6g} W; "
                  f"reference peak={report['thermal']['peak_c']:.6g} C")
            print(f"Uncalibrated thermal model; timing not implemented. Report: {args.output / 'report.json'}")
        return 0
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
