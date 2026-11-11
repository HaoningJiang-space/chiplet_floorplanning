"""Aggregate local evidence and test exact clock-control effects without rerunning STA."""

import argparse
import hashlib
import json
from pathlib import Path
import re

from validation.interface_bridge import TOLERANCE_NS
from validation.sources import write_json


def summarize(root):
    paths = {name: root / relative for name, relative in (
        ("bridge", "bridge-reviewed/report.json"), ("characterization", "characterization/report.json"),
        ("thermal", "open-thermal/report.json"))}
    sources = {name: json.loads(path.read_text()) for name, path in paths.items()}
    bridge, characterization, thermal = [sources[k] for k in ("bridge", "characterization", "thermal")]
    baseline = bridge["cases"]["gpio_length_3mm"]["bridge"]["paths"]
    controls = {}
    # Ideal-event arithmetic under the frozen 20 ns, 50% duty baseline.
    # These expectations do not use an observed slack to choose a requirement.
    for name, deltas in (("gpio_duty_40", (-2, 2)), ("gpio_duty_60", (2, -2)),
                         ("gpio_period_40ns", (10, 10)), ("gpio_uncertainty", (-0.1, -0.05)),
                         ("gpio_setup_failure_2ns", (-9, -9))):
        rows = {}
        propagation_errors = []
        arc_identity_same = True
        for key, observed in bridge["cases"][name]["bridge"]["paths"].items():
            expected = deltas[0 if key.startswith("setup") else 1]
            change = observed["slack_ns"] - baseline[key]["slack_ns"]
            rows[key] = dict(expected_delta_ns=expected, observed_delta_ns=change,
                             absolute_error_ns=abs(change - expected))
            for lane in ("data_path", "clock_path"):
                a, b = observed[lane], baseline[key][lane]
                arc_identity_same &= [(p["pin"], p["cell"], p["edge"]) for p in a] == [(p["pin"], p["cell"], p["edge"]) for p in b]
                if len(a) != len(b):
                    arc_identity_same = False
                for first, second in zip(a, b):
                    propagation_errors.extend(abs(first[field] - second[field]) for field in ("increment_ns", "slew_ns"))
        controls[name] = dict(paths=rows, same_pin_arc_identities=arc_identity_same,
                              max_propagation_change_ns=max(propagation_errors),
                              passed=arc_identity_same and max(propagation_errors) <= TOLERANCE_NS and
                              all(r["absolute_error_ns"] <= TOLERANCE_NS for r in rows.values()))
    cases = []
    for name, record in bridge["cases"].items():
        if not record["contract_passed"]:
            cases.append(dict(name=name, family=record["model_family"], status="rejected", reason=record["reason"]))
            continue
        fields = record["bridge"]["paths"]
        cases.append(dict(name=name, family=record["model_family"], status=record["outcome"],
                          setup_slack_ns=min(v["slack_ns"] for k, v in fields.items() if k.startswith("setup")),
                          hold_slack_ns=min(v["slack_ns"] for k, v in fields.items() if k.startswith("hold")),
                          max_path_error_ns=record["bridge"]["max_abs_error_ns"],
                          max_core_lookup_error_ns=max(r["max_abs_error_ns"] for r in record["core_table_checks"]),
                          receiver_queries_in_domain=record["receiver_domain_passed"],
                          used_core_queries_in_domain=record["core_domain_passed"],
                          core_query_count=len(record["core_table_checks"]),
                          pad_query_count=len(record.get("pad_table_checks", [])),
                          timing_met=record["timing_met"]))
    thermals = []
    for case in thermal["cases"]:
        conv = case["convergence"]
        final = conv["meshes"][-1]
        thermals.append(dict(name=case["name"], chiplets=case["chiplets"],
                             total_power_w=final["total_power_w"], peak_c=final["peak_c"],
                             final_peak_grid_change_k=conv["final_peak_change_k"],
                             energy_balance_error_w=final["energy_balance_error_w"],
                             reference_temperature_error_k=case.get("errors", {}).get("max_temperature_error_k"),
                             numerical_checks_passed=case["passed"], physical_calibration=False))
    electrical_evidence = {}
    for name, folder in (("gpio_length_12mm", "gpio_length_12mm_source"),
                          ("original_direction", "gpio_original_direction")):
        location = paths["bridge"].parent / folder
        log = (location / "sta.log").read_text()
        rejection = json.loads((location / "rejection.json").read_text())
        violations = [line.strip() for line in log.split("Startpoint:", 1)[0].splitlines() if "(VIOLATED)" in line]
        electrical_evidence[name] = dict(outcome="electrical_rejected", violations=violations,
                                         log_sha256=hashlib.sha256((location / "sta.log").read_bytes()).hexdigest(),
                                         passed=bool(violations) and "electrical design-rule" in rejection["reason"] and
                                         not re.search(r"(?m)^(?:Error|Warning):", log),
                                         execution_evidence="run_timing checks returncode before creating electrical rejection.json")
    checks = dict(characterization=characterization["software_checks_passed"],
                  interface_bridge=bridge["software_checks_passed"], thermal=thermal["passed"],
                  quantitative_clock_controls=all(r["passed"] for r in controls.values()),
                  electrical_negative_evidence=all(r["passed"] for r in electrical_evidence.values()))
    return dict(software_checks_passed=all(checks.values()), checks=checks,
                source=bridge["source"], source_reports_sha256={k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in paths.items()},
                sta_sha256=bridge["sta_sha256"], circuit_families=2, timing_parameter_cases=len(cases),
                checked_timing_paths=sum(4 for r in cases if r["status"] != "rejected"),
                core_nldm_queries=sum(r.get("core_query_count", 0) for r in cases),
                pad_nldm_queries=sum(r.get("pad_query_count", 0) for r in cases),
                receiver_constraint_queries=sum(4 for r in cases if r["status"] != "rejected"),
                cases=cases, quantitative_controls=controls, negative_controls=bridge["controls"],
                electrical_negative_evidence=electrical_evidence,
                thermal_cases=thermals, gpio_thermal=bridge["gpio_thermal"],
                temperature_experiments=characterization["temperature"],
                all_used_queries_in_domain=bridge["all_models_in_domain"],
                physical_d2d_validation=False, thermal_physical_calibration=False,
                propagation_validation="conditional NLDM checks at STA slew/Ceff; path accounting reuses STA increments",
                scope="local parameter experiments on two timing circuits; four thermal input cases; no joint-optimization necessity claim")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    args = p.parse_args()
    report = summarize(args.root)
    write_json(args.root / "summary.json", report)
    print(json.dumps({k: report[k] for k in ("software_checks_passed", "checks", "timing_parameter_cases",
                                            "checked_timing_paths", "all_used_queries_in_domain")}, indent=2))
    return 0 if report["software_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
