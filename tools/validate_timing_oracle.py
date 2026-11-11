"""Independent fixed-delay event oracle versus source-synchronous OpenSTA paths."""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import platform
import subprocess

from validation.sources import git_revision, write_json
from validation.timing_fixture import NETLIST, library, script
from validation.timing_oracle import Contract, early_corner, experiments, expected_paths
from validation.timing_report import compare_builds, extract

TOLERANCE_NS = 1e-5


def compare(actual, contract, early=None):
    expected = expected_paths(contract, early)
    errors, normalized = {}, {}
    for key, reference in expected.items():
        check, transition = key.split("_")
        index = ("rise", "fall").index(transition)
        # Fixed BEFORE inspecting any report: OpenSTA 2.2 presents setup at
        # launch 0 and hold at launch P, both with capture at the first fall.
        # Never choose a per-path integer shift by minimizing observed error.
        shift = 0.0 if check == "setup" else contract.period_ns
        normalized[key] = {
            field: actual[key][field] - (0 if field == "slack_ns" else shift)
            for field in reference}
        for field, value in reference.items():
            errors[f"{key}.{field}"] = abs(normalized[key][field] - value)
        data_model = contract if check == "setup" else (early or contract)
        clock_model = (early or contract) if check == "setup" else contract
        for pin, delay in (("tx_reg/Q", data_model.cq_ns[index]),
                            ("tx_data/Y", data_model.data_ns[index]),
                            ("tx_clock/Y", clock_model.clock_ns[1]),
                            ("rx_clock/Y", clock_model.inverter_ns[0])):
            fields = actual[key]["pins"][pin]
            errors[f"{key}.{pin}.delay_ns"] = abs(fields["delay_ns"] - delay)
            errors[f"{key}.{pin}.slew_ns"] = abs(fields["slew_ns"] - 0.1)
            if fields["cap_pf"] is None or abs(fields["cap_pf"] - 0.01) > 1e-6:
                raise ValueError(f"{key}.{pin}: wrong fixture capacitance")
    mismatches = {k: v for k, v in errors.items() if v > TOLERANCE_NS}
    if mismatches:
        raise ValueError("analytic mismatch: " + json.dumps(mismatches, sort_keys=True))
    return dict(expected=expected, normalized_observed=normalized,
                max_abs_error_ns=max(errors.values()),
                checked_numeric_fields=len(errors), observed=actual)


def run_case(sta, out, contract, mutation=None, min_max=False):
    out.mkdir()
    early = early_corner(contract) if min_max else None
    fixture_contract = (replace(contract, clock_ns=contract.clock_ns[::-1])
                        if mutation == "swapped_clock_arcs" else contract)
    content = library(fixture_contract)
    if mutation == "wrong_ff_polarity":
        content = content.replace('clocked_on : "CK"', 'clocked_on : "!CK"')
        content = content.replace("rising_edge", "falling_edge")
    tcl = script(contract, mutation, min_max)
    if mutation == "wrong_endpoint":
        tcl = tcl.replace("[get_pins rx_reg/D]", "[get_pins tx_reg/D]")
    if mutation == "swapped_min_max":
        tcl = tcl.replace("-min early.lib", "-max early.lib").replace("-max fixture.lib", "-min fixture.lib")
    inputs = {"fixture.lib": content, "lane.v": NETLIST, "run.tcl": tcl}
    if early:
        inputs["early.lib"] = library(early).replace("semantic_fixture", "semantic_early")
    hashes = {}
    for name, text in inputs.items():
        data = text.encode("utf-8")
        (out / name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    run = subprocess.run([str(sta), "-no_init", "-exit", "run.tcl"], cwd=out,
                         capture_output=True, text=True, timeout=30)
    log = run.stdout + run.stderr
    (out / "sta.log").write_text(log)
    result = dict(contract=asdict(contract), early=asdict(early) if early else None,
                  mutation=mutation, input_sha256=hashes, returncode=run.returncode)
    try:
        if run.returncode:
            raise RuntimeError(f"OpenSTA process failed with {run.returncode}")
        result.update(compare(extract(log), contract, early))
        result["contract_accepted"] = True
    except ValueError as error:
        result.update(contract_accepted=False, rejection_reason=str(error))
    write_json(out / "comparison.json", result)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sta", type=Path, default=Path("local/upstream/OpenSTA/app/sta"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--reference", type=Path,
                   help="Frozen Windows receipt for cross-build field comparison")
    args = p.parse_args()
    sta = args.sta.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    cases = {name: run_case(sta, args.output / name, c)
             for name, c in experiments().items()}
    cases["early_late"] = run_case(sta, args.output / "early_late", Contract(), min_max=True)
    mutations = ("missing_invert", "missing_generated_clock", "ideal_capture",
                 "wrong_ff_polarity", "swapped_clock_arcs", "wrong_endpoint",
                 "missing_constraints", "swapped_min_max")
    negative = {name: run_case(sta, args.output / ("negative_" + name), Contract(), name,
                              min_max=(name == "swapped_min_max")) for name in mutations}
    checks = {name: r["contract_accepted"] for name, r in cases.items()}
    checks.update({"reject_" + name: not r["contract_accepted"] for name, r in negative.items()})
    for check in ("setup", "hold"):
        case = cases[check + "_violation"]
        checks[check + "_negative_slack_preserved"] = (
            case["contract_accepted"] and all(case["observed"][f"{check}_{edge}"]["slack_ns"] < 0
                                              for edge in ("rise", "fall")))
    cross_build = None
    if args.reference:
        reference = json.loads(args.reference.read_text())["timing_oracle"]["cases"]
        try:
            cross_build = compare_builds(cases, reference, TOLERANCE_NS)
        except (KeyError, ValueError) as error:
            cross_build = dict(passed=False, reason=str(error))
        cross_build["reference_sha256"] = hashlib.sha256(args.reference.read_bytes()).hexdigest()
        checks["cross_build_full_paths"] = cross_build["passed"]
    report = dict(software_checks_passed=all(checks.values()), checks=checks,
                  source=git_revision(Path(__file__).resolve().parents[1]),
                  platform=platform.platform(), executable_sha256=hashlib.sha256(sta.read_bytes()).hexdigest(),
                  sta_version=subprocess.check_output([str(sta), "-version"], text=True).strip(),
                  tolerance_ns=TOLERANCE_NS, cases=cases, negative_controls=negative,
                  cross_build=cross_build,
                  scope="Synthetic fixed-delay source-synchronous semantics only",
                  physical_d2d_validation=False, temperature_feedback_validation=False)
    write_json(args.output / "report.json", report)
    print(json.dumps({"software_checks_passed": report["software_checks_passed"], "checks": checks}, indent=2))
    return 0 if report["software_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
