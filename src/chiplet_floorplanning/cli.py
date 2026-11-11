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


def evaluate(case, output, timing_options=None, coupling_options=None):
    output = Path(output)
    if output.exists():
        raise ValueError(f"output already exists; choose a new directory: {output}")
    power, blocks = rasterize(case)
    temperature, thermal = solve_steady(case, power)
    links = estimate_links(case)
    timing = {"status": "not_run", "setup_slack_ns": None, "hold_slack_ns": None}
    if timing_options and coupling_options:
        raise ValueError('choose fixed-library timing or local-temperature timing')
    if timing_options:
        from .timing import run_timing
        timing = run_timing(case, output / "timing", **timing_options)
    if coupling_options:
        from .characterization import run_coupled_timing
        timing = run_coupled_timing(case, temperature, output, **coupling_options)
    input_w = sum(block["input_w"] for block in blocks)
    canonical = (json.dumps(case.input_data, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    report = {
        "schema_version": 1,
        "case": case.name,
        "scope": "fixed_layout_assumption_driven_reference",
        "validation": {"geometry": "passed", "power_conservation": "passed",
                       "thermal_residual_and_energy_balance": "passed",
                       "thermal_external_validation": "not_run",
                       "cross_die_setup_hold": timing["status"]},
        "power": {"input_w": input_w, "mapped_w": float(power.sum()),
                  "error_w": float(power.sum()) - input_w, "blocks": blocks},
        "thermal": thermal,
        "links": links,
        "timing": timing,
        "qualification": {"physical_package_calibration": "not_completed_no_measurement_data",
                          "full_PVT_signoff": "not_completed",
                          "pad_PHY_qualification": "not_completed",
                          "temperature_interpolation_holdout": "not_completed",
                          "complete_package_signoff": False},
        "provenance": {"input_snapshot_sha256": hashlib.sha256(canonical).hexdigest(),
                       "tool_version": __version__, "source": source_revision(),
                       "python": platform.python_version(), "numpy": np.__version__,
                       "scipy": scipy.__version__, "timestamp_utc": datetime.now(timezone.utc).isoformat()},
    }
    encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if not timing_options and not coupling_options:
        output.mkdir(parents=True, exist_ok=False)
    # Hash and persist the same bytes; text mode translates LF to CRLF on Windows.
    (output / "input.json").write_bytes(canonical)
    xs, ys = case.mesh.x_centers_mm, case.mesh.y_centers_mm
    widths, heights, areas = case.mesh.widths_mm, case.mesh.heights_mm, case.mesh.areas_mm2
    with (output / "grid.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["ix", "iy", "x_center_mm", "y_center_mm", "power_w", "power_density_w_mm2", "temperature_c", "width_mm", "height_mm"])
        for y in range(case.ny):
            for x in range(case.nx):
                writer.writerow([x, y, xs[x], ys[y], power[y, x], power[y, x] / areas[y, x],
                                 temperature[y, x] if np.isfinite(temperature[y, x]) else "",
                                 widths[x], heights[y]])
    # Written last: its presence indicates completion of the other artifacts.
    (output / "report.json").write_text(encoded, encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fixed-layout chiplet evaluation (uncalibrated reference model)")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate geometry, units, sources, and connectivity")
    validate.add_argument("case", type=Path)
    run = subparsers.add_parser("evaluate", help="evaluate power/thermal and optionally real-library lane timing")
    run.add_argument("case", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--sta", type=Path, help="enable the SKY130 to GF180 core-cell timing harness")
    run.add_argument("--sky-lib", type=Path)
    run.add_argument("--gf-lib", type=Path)
    run.add_argument("--period-ns", type=float, default=20.0)
    run.add_argument('--sky-pad-lib', type=Path)
    run.add_argument('--gf-pad-lib', type=Path)
    run.add_argument('--pad-direction', choices=['sky130_to_gf180', 'gf180_to_sky130'], default='sky130_to_gf180')
    run.add_argument('--temperature-model-root', type=Path, help='enable per-instance SKY FF 1.65 V / GF FF 1.98 V core interpolation')
    run.add_argument('--instance-locations', type=Path, help='JSON with coordinate_unit=mm and die-local positions for all five instances')
    args = parser.parse_args(argv)
    try:
        case = load_case(args.case)
        if args.command == "validate":
            print(f"VALID {case.name}: {len(case.dies)} chiplets, {len(case.links)} links")
        else:
            timing_options, coupling_options = None, None
            if args.temperature_model_root or args.instance_locations:
                if not all((args.sta, args.temperature_model_root, args.instance_locations)):
                    raise ValueError('--sta, --temperature-model-root and --instance-locations are required together')
                if any((args.sky_lib, args.gf_lib, args.sky_pad_lib, args.gf_pad_lib)) or args.pad_direction != 'sky130_to_gf180':
                    raise ValueError('temperature profile uses its own core models; pad temperature libraries are unavailable')
                coupling_options = dict(sta=args.sta, model_root=args.temperature_model_root,
                                        locations=json.loads(args.instance_locations.read_text()), period_ns=args.period_ns)
            else:
                if (any((args.sta, args.sky_lib, args.gf_lib, args.sky_pad_lib, args.gf_pad_lib)) or args.pad_direction != 'sky130_to_gf180') and not all((args.sta, args.sky_lib, args.gf_lib)):
                    raise ValueError('--sta, --sky-lib and --gf-lib must be supplied together')
                if args.sta:
                    timing_options = dict(sta=args.sta, sky_lib=args.sky_lib, gf_lib=args.gf_lib,
                                          sky_pad_lib=args.sky_pad_lib, gf_pad_lib=args.gf_pad_lib, period_ns=args.period_ns,
                                          pad_direction=args.pad_direction)
            report = evaluate(case, args.output, timing_options, coupling_options)
            print(f"{case.name}: power={report['power']['mapped_w']:.6g} W; "
                  f"reference peak={report['thermal']['peak_c']:.6g} C")
            print(f"Uncalibrated thermal model; timing={report['timing']['status']}. Report: {args.output / 'report.json'}")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
