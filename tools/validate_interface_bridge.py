"""Local multicase real-library bridge; no remote jobs or physical signoff."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from chiplet_floorplanning.liberty_checks import check_pad_tables
from chiplet_floorplanning.model import load_case, parse_case
from chiplet_floorplanning.power import rasterize
from chiplet_floorplanning.thermal import solve_steady
from chiplet_floorplanning.timing import parse_sta_log, run_timing
from validation.interface_bridge import audit, audit_core_tables, audit_pad_path_identity, diagnostics, library_for_receiver
from validation.sources import git_revision, write_json


def replay(source, out, sta, *, period_ns=20.0, duty=0.5,
           setup_uncertainty_ns=0.0, hold_uncertainty_ns=0.0, mutation=None):
    source, out = Path(source), Path(out)
    metadata = json.loads((source / "timing.json").read_text())
    pads = metadata["status"] == "analyzed_GPIO_pad_harness"
    receiver_library, receiver_cell = library_for_receiver(source)
    out.mkdir(parents=True, exist_ok=False)
    for name in ("lane.v", "wire_models.lib", "package.spef"):
        shutil.copyfile(source / name, out / name)
    script = (source / "run.tcl").read_text()
    script, count = re.subn(r"(?m)^create_clock -name launch .*?$",
                           f"create_clock -name launch -period {period_ns} -waveform {{0 {period_ns*duty}}} [get_ports clk]", script)
    if count != 1:
        raise ValueError("expected exactly one primary-clock declaration")
    script = script.replace("set_propagated_clock [all_clocks]",
                            "set_propagated_clock [all_clocks]\n"
                            f"set_clock_uncertainty -setup {setup_uncertainty_ns} [get_clocks capture]\n"
                            f"set_clock_uncertainty -hold {hold_uncertainty_ns} [get_clocks capture]")
    script, count = re.subn(r"(?m)^exit[ \t]*$", "", script)
    if count != 1:
        raise ValueError("expected exactly one final exit")
    script += diagnostics(pads)
    if mutation == "wrong_inversion":
        script = script.replace(" -invert ", " ")
    elif mutation == "missing_generated_clock":
        script = re.sub(r"(?m)^create_generated_clock.*\n", "", script)
    elif mutation == "wrong_endpoint":
        script = script.replace("[get_pins rx_reg/D]", "[get_pins tx_reg/D]")
    elif mutation == "missing_output_constraint":
        script = re.sub(r"(?m)^set_output_delay.*\n", "", script)
    elif mutation == "wrong_uncertainty":
        script = script.replace(f"-setup {setup_uncertainty_ns} [get_clocks capture]",
                                f"-setup {setup_uncertainty_ns+0.1} [get_clocks capture]")
    (out / "run.tcl").write_bytes(script.encode())
    run = subprocess.run([str(Path(sta).resolve()), "-no_init", "-exit", "run.tcl"], cwd=out,
                         capture_output=True, text=True, timeout=120)
    log = run.stdout + run.stderr
    (out / "sta.log").write_text(log)
    record = dict(source_run=str(source), period_ns=period_ns, duty=duty,
                  setup_uncertainty_ns=setup_uncertainty_ns, hold_uncertainty_ns=hold_uncertainty_ns,
                  mutation=mutation, model_family="gpio" if pads else "core",
                  libraries=metadata["libraries"], receiver_cell=receiver_cell,
                  input_sha256={name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                                for name in ("lane.v", "wire_models.lib", "package.spef", "run.tcl")})
    if run.returncode:
        write_json(out / "bridge.json", {**record, "outcome": "tool_execution_failure",
                                          "contract_passed": False, "returncode": run.returncode})
        raise RuntimeError("OpenSTA process failed: " + str(out))
    try:
        # Preserve the existing wire annotation, electrical and pad-domain gates.
        legacy_log = log.split("BRIDGE_CHECKS_BEGIN", 1)[0]
        parse_sta_log(legacy_log, metadata["links"])
        if pads:
            libpaths = re.findall(r"(?m)^read_liberty\s+\{([^}]+)\}", script)
            record["pad_table_checks"] = check_pad_tables(legacy_log, libpaths[2], libpaths[3])
        record["bridge"] = audit(log, receiver_library, receiver_cell, period_ns, duty,
                                  setup_uncertainty_ns, hold_uncertainty_ns, pads)
        record["core_table_checks"] = audit_core_tables(log, out, record["bridge"], pads)
        if pads:
            audit_pad_path_identity(record["bridge"], record["pad_table_checks"], libpaths[2], libpaths[3])
        record["contract_passed"] = True
        record["receiver_domain_passed"] = record["bridge"]["all_receiver_queries_in_domain"]
        record["core_domain_passed"] = all(r["inside_table_domain"] for r in record["core_table_checks"] if r["used_in_paths"])
        record["timing_met"] = all(p["slack_ns"] >= 0 for p in record["bridge"]["paths"].values())
        record["analysis_status"] = ("in_domain" if record["receiver_domain_passed"] and record["core_domain_passed"] else
                                     "core_or_constraint_extrapolation")
        record["outcome"] = ("table_domain_rejected" if record["analysis_status"] != "in_domain" else
                             "valid_timing_pass" if record["timing_met"] else "valid_timing_violation")
    except ValueError as error:
        record.update(contract_passed=False, receiver_domain_passed=None, core_domain_passed=None, timing_met=None,
                      analysis_status="rejected", outcome="semantic_mismatch", reason=str(error))
    write_json(out / "bridge.json", record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("local"))
    parser.add_argument("--sta", type=Path, required=True)
    parser.add_argument("--characterization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cases, controls, thermal = {}, {}, {}
    core_files = sorted(args.characterization.rglob("timing.json"))
    if len(core_files) != 33:
        raise ValueError(f"expected 33 characterized core runs, found {len(core_files)}")
    for file in core_files:
        name = "core_" + "_".join(file.parent.relative_to(args.characterization).parts)
        cases[name] = replay(file.parent, args.output / name, args.sta)
        print(name, cases[name]["analysis_status"], flush=True)
    base = load_case("examples/low_speed_gpio.json")
    models = args.root / "pdk-v03"
    options = dict(sta=args.sta, sky_lib=args.root / "pdk/sky130_tt_1v8.lib",
                   gf_lib=models / "gf_core_tt_3v3.lib", sky_pad_lib=models / "sky_io_tt_1v8_3v3.lib",
                   gf_pad_lib=models / "gf_bi_t_tt_3v3_assembled.lib", pad_direction="gf180_to_sky130")
    nominal = None
    for length in (0.1, 1.0, 3.0, 6.0, 12.0):
        raw = copy.deepcopy(base.input_data)
        raw["chiplets"][1]["placement_mm"]["x"] = 4 + length
        raw["package_mm"]["width"] = max(12, 8 + length)
        for link in raw["links"]:
            link["route_points_mm"][-1][0] = 4 + length
        case = parse_case(raw)
        name = f"gpio_length_{length:g}mm"
        source = args.output / (name + "_source")
        write_json(args.output / (name + "_input.json"), raw)
        power, _ = rasterize(case)
        _, heat = solve_steady(case, power)
        thermal[name] = {k: heat[k] for k in ("peak_c", "energy_balance_error_w")}
        try:
            run_timing(case, source, **options)
        except ValueError as error:
            controls[name] = dict(expected_rejection=length == 12 and "electrical design-rule" in str(error),
                                  outcome="electrical_rejected" if "electrical design-rule" in str(error) else "unexpected_rejection",
                                  reason=str(error))
            continue
        cases[name] = replay(source, args.output / name, args.sta)
        if length == 3:
            nominal = source
        print(name, cases[name]["analysis_status"], flush=True)
    if nominal is None:
        raise ValueError("nominal GPIO unexpectedly rejected")
    for name, config in (
        ("gpio_duty_40", {"duty": 0.4}), ("gpio_duty_60", {"duty": 0.6}),
        ("gpio_period_40ns", {"period_ns": 40.0}),
        ("gpio_uncertainty", {"setup_uncertainty_ns": 0.1, "hold_uncertainty_ns": 0.05}),
        ("gpio_setup_failure_2ns", {"period_ns": 2.0}),
    ):
        cases[name] = replay(nominal, args.output / name, args.sta, **config)
        print(name, cases[name]["analysis_status"], flush=True)
    try:
        run_timing(base, args.output / "gpio_original_direction", **{**options,
                   "pad_direction": "sky130_to_gf180", "gf_pad_lib": models / "gf_io_tt_3v3_assembled.lib"})
        controls["original_direction"] = dict(expected_rejection=False)
    except ValueError as error:
        controls["original_direction"] = dict(expected_rejection="electrical design-rule" in str(error),
                                              outcome="electrical_rejected" if "electrical design-rule" in str(error) else "unexpected_rejection", reason=str(error))
    for mutation in ("wrong_inversion", "missing_generated_clock", "wrong_endpoint",
                     "missing_output_constraint", "wrong_uncertainty"):
        result = replay(nominal, args.output / ("negative_" + mutation), args.sta, mutation=mutation)
        controls[mutation] = dict(expected_rejection=not result["contract_passed"],
                                  reason=result.get("reason"), category="structural_or_constraint_negative")
    checks = dict(all_cases_executed=len(cases) == 42,
                  all_contracts_passed=all(r["contract_passed"] for r in cases.values()),
                  negative_controls_detected=all(r["expected_rejection"] for r in controls.values()),
                  negative_setup_preserved=cases["gpio_setup_failure_2ns"]["contract_passed"] and
                      not cases["gpio_setup_failure_2ns"]["timing_met"])
    report = dict(software_checks_passed=all(checks.values()), checks=checks, cases=cases,
                  controls=controls, gpio_thermal=thermal, source=git_revision(Path.cwd()),
                  sta_sha256=hashlib.sha256(args.sta.read_bytes()).hexdigest(),
                  independent_netlist_families=2, parameter_cases=len(cases),
                  all_models_in_domain=all(r["receiver_domain_passed"] and r["core_domain_passed"] for r in cases.values()),
                  physical_d2d_validation=False, temperature_interpolation_physical_validation=False,
                  scope="two circuit families with parameter scans; not 42 independent hardware designs")
    write_json(args.output / "report.json", report)
    print(json.dumps(checks, indent=2))
    return 0 if report["software_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
