"""Predeclared passive-channel and real-Liberty lane controls."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import shutil
import hashlib

import numpy as np
from scipy.signal import lsim

from chiplet_floorplanning.interconnect import estimate_links
from chiplet_floorplanning.model import load_case
from chiplet_floorplanning.timing import run_timing, parse_sta_log


def negative_controls(root, sta, links):
    checks = {}
    for name in ("missing_spef", "unannotated", "unknown_cell"):
        dest = root / ("negative_" + name)
        dest.mkdir()
        for file in (root / "base").iterdir():
            if file.suffix in (".v", ".lib", ".spef", ".tcl"):
                shutil.copyfile(file, dest / file.name)
        if name == "missing_spef":
            (dest / "package.spef").unlink()
        elif name == "unannotated":
            path = dest / "run.tcl"
            path.write_text(path.read_text().replace("read_spef package.spef", "# intentionally unannotated negative control"))
        else:
            path = dest / "lane.v"
            path.write_text(path.read_text().replace("sky130_fd_sc_hd__dfxtp_1", "missing_cell"))
        result = subprocess.run([str(sta.resolve()), "-exit", "run.tcl"], cwd=dest, capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        (dest / "sta.log").write_text(log)
        try:
            parse_sta_log(log, links)
        except ValueError:
            checks[name + "_rejected"] = True
        else:
            checks[name + "_rejected"] = False
    return checks


def rc_compare(output, ngspice, resistance, capacitance_pf):
    output.mkdir()
    segments = 8
    delay, transition = 200e-12, 100e-12
    end, step = 2e-9, 0.2e-12
    deck = ["Passive RC lane: 1 V normalization", ".option reltol=1e-7 abstol=1e-15 vntol=1e-9",
            f"Vsrc n0 0 PULSE(0 1 {delay} {transition} {transition} 3e-9 6e-9)"]
    for i in range(segments + 1):
        cap = capacitance_pf * 1e-12 / segments * (0.5 if i in (0, segments) else 1)
        deck.append(f"C{i} n{i} 0 {cap:.15g}")
        if i:
            deck.append(f"R{i} n{i-1} n{i} {resistance / segments:.15g}")
    deck += [f".tran {step} {end} 0 {step}"]
    for label, value in [("t20", 0.2), ("t50", 0.5), ("t80", 0.8)]:
        deck.append(f".measure tran {label} WHEN v(n{segments})={value} RISE=1")
    deck.append(".end")
    (output / "channel.cir").write_text("\n".join(deck)+"\n")
    run = subprocess.run([str(ngspice), "-b", "channel.cir"], cwd=output, capture_output=True, text=True, timeout=60)
    log = run.stdout + run.stderr
    (output / "ngspice.log").write_text(log)
    found = {key: float(value) for key, value in re.findall(r"(t20|t50|t80)\s*=\s*([+0-9.eE-]+)", log)}
    if run.returncode or found.keys() != {"t20", "t50", "t80"}:
        raise ValueError(f"ngspice measurement failed: {output}")
    # Independent nodal ODE: C dV/dt + G V = g*Vin at first node.
    g = segments / resistance
    cap = np.full(segments, capacitance_pf * 1e-12 / segments)
    cap[-1] *= 0.5
    G = np.diag(np.full(segments, 2 * g)) + np.diag(np.full(segments-1, -g), 1) + np.diag(np.full(segments-1, -g), -1)
    G[-1, -1] = g
    A = -G / cap[:, None]
    B = np.zeros(segments); B[0] = g / cap[0]
    C = np.zeros(segments); C[-1] = 1
    time = np.linspace(0, end, round(end / step) + 1)
    wave = np.clip((time-delay) / transition, 0, 1)
    _, receiver, _ = lsim((A, B[:, None], C[None, :], np.zeros((1, 1))), wave, time)
    expected = {key: float(np.interp(level, receiver, time)) for key, level in [("t20", 0.2), ("t50", 0.5), ("t80", 0.8)]}
    error = abs(found["t50"]-expected["t50"])
    np.savez(output / "state_space.npz", time_s=time, input_v=wave, receiver_v=receiver)
    return {"r_ohm": resistance, "c_pf": capacitance_pf, "ngspice_crossings_s": found,
            "state_space_crossings_s": expected, "crossing_error_ps": error*1e12,
            "ngspice_slew_20_80_ps": (found["t80"]-found["t20"])*1e12,
            "state_space_slew_20_80_ps": (expected["t80"]-expected["t20"])*1e12,
            "passed": error <= max(1e-12, 0.01*(expected["t50"]-delay))}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--case", default="examples/layered_two_chiplets.json")
    p.add_argument("--sta", type=Path, default=Path("local/upstream/OpenSTA/app/sta"))
    p.add_argument("--ngspice", type=Path, default=Path("local/bin-root/usr/bin/ngspice"))
    p.add_argument("--sky-lib", type=Path, default=Path("local/pdk/sky130_tt_1v8.lib"))
    p.add_argument("--gf-lib", type=Path, default=Path("local/pdk/gf180_tt_1v8.lib"))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    case = load_case(args.case)
    runs = {}
    for name, options in [("base", {}), ("data_resistance", {"data_r_scale": 100}),
                          ("clock_resistance", {"clock_r_scale": 100}), ("longer_period", {"period_ns": 24}),
                          ("short_period", {"period_ns": 2})]:
        runs[name] = run_timing(case, args.output / name, args.sta, args.sky_lib, args.gf_lib, **options)
    base, data, clock = (runs[key] for key in ("base", "data_resistance", "clock_resistance"))
    checks = {"data_R_reduces_setup": data["setup_slack_ns"] < base["setup_slack_ns"],
              "data_R_improves_hold": data["hold_slack_ns"] > base["hold_slack_ns"],
              "clock_R_improves_setup": clock["setup_slack_ns"] > base["setup_slack_ns"],
              "clock_R_reduces_hold": clock["hold_slack_ns"] < base["hold_slack_ns"],
              "half_period_setup_shift": abs(runs["longer_period"]["setup_slack_ns"]-base["setup_slack_ns"]-2) <= 1e-5,
              "short_period_violation_retained": runs["short_period"]["setup_slack_ns"] < 0}
    checks.update(negative_controls(args.output, args.sta, estimate_links(case)))
    link = estimate_links(case)[0]
    passive = [rc_compare(args.output / "rc_nominal", args.ngspice.resolve(), link["assumed_r_ohm"], link["assumed_c_pf"]),
               rc_compare(args.output / "rc_stress", args.ngspice.resolve(), 120, 0.8)]
    report = {"passed": all(checks.values()) and all(r["passed"] for r in passive),
              "scope": "real_Liberty_core_cell_timing_and_passive_RC_not_pad_or_PHY_signoff", "checks": checks,
              "timing": {key: {f: run[f] for f in ("setup_slack_ns", "hold_slack_ns", "period_ns")} for key, run in runs.items()},
              "passive_channel": passive}
    report["ngspice_sha256"] = hashlib.sha256(args.ngspice.read_bytes()).hexdigest()
    report["input_sha256"] = hashlib.sha256(Path(args.case).read_bytes()).hexdigest()
    (args.output / "report.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
