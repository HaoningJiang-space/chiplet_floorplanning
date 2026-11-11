"""Same-mode GPIO transistor diagnostics; retain failed qualification gates."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess

import numpy as np

from chiplet_floorplanning.liberty_checks import (
    active_arc,
    lookup,
    read_table,
    unique_group,
)
from validation.pad_sources import MATCHED_LIBERTY, digest, prepare
from validation.pad_spice import (
    closure,
    conversion_audit,
    deck,
    differences,
    log_diagnostics,
    measure_waveform,
    pin_connections,
    subcircuits,
)
from validation.sources import git_revision, verify, write_json


def definitions(root, pdk_root):
    result = {}
    for side, files, top, library, output in (
        (
            "gf180",
            [root / "gf180/bi_t.spice"],
            "gf180mcu_fd_io__bi_t",
            pdk_root / "gf_bi_t_tt_3v3.lib",
            "PAD",
        ),
        (
            "sky130",
            [
                root / f"sky130A/libs.ref/sky130_fd_io/spice/{f}.spice"
                for f in ("sky130_fd_io", "sky130_ef_io")
            ],
            "sky130_ef_io__gpiov2_pad",
            pdk_root / "sky_io_tt_1v8_3v3.lib",
            "IN",
        ),
    ):
        text = "\n".join(f.read_text() for f in files)
        blocks = subcircuits(text)
        pins = blocks[top]["pins"]
        mapping, domains = pin_connections(side, pins, library.read_text())
        primitives = (
            [root / "gf180/sm141064.ngspice"]
            if side == "gf180"
            else list((root / "sky130A/libs.ref/sky130_fd_pr/spice").glob("*.spice"))
        )
        declared = {
            s.lower()
            for file in primitives
            for s in re.findall(r"(?im)^\.subckt\s+(\S+)", file.read_text())
        }
        result[side] = dict(
            pins=pins,
            mapping=mapping,
            control_supply_domains=domains,
            closure=closure(blocks, top, declared),
            library=str(library),
            cell=top,
            output=output,
        )
    return result


def simulate(config, models, root, ngspice, output, init, *, content=None):
    """Execute and archive a deck; explicit diagnostic overrides retain byte hashes."""
    side = config["side"]
    name = "_".join(
        str(config[k])
        for k in (
            "side",
            "temperature_c",
            "input_slew_ns",
            "external_load_pf",
            "max_step_ps",
        )
    )
    folder = output / name
    folder.mkdir()
    info = models[side]
    if content is None:
        content = deck(
            root,
            side,
            info["mapping"],
            info["pins"],
            **{k: v for k, v in config.items() if k != "side"},
        )
    (folder / "deck.sp").write_bytes(content.encode("utf-8"))
    command = [str(ngspice), "-n"]
    if side == "sky130":
        command += ["-D", "ngbehavior=hsa"]
    command += ["-b", "deck.sp"]
    try:
        run = subprocess.run(
            command,
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=240,
            env={**os.environ, "SPICE_SCRIPTS": str(init), "OMP_NUM_THREADS": "1"},
        )
        log, returncode = run.stdout + run.stderr, run.returncode
    except subprocess.TimeoutExpired as error:

        def decode(value):
            return (
                value.decode(errors="replace")
                if isinstance(value, bytes)
                else (value or "")
            )

        log = (
            decode(error.stdout)
            + decode(error.stderr)
            + "\nERROR: diagnostic timed out after 240 s\n"
        )
        returncode = None
    (folder / "ngspice.log").write_bytes(log.encode("utf-8"))
    record = dict(
        config,
        name=name,
        deck_sha256=digest(content.encode()),
        log_sha256=digest(log.encode()),
        simulator_returncode=returncode,
        diagnostics=log_diagnostics(log),
        simulation_completed=False,
    )
    wave = folder / "waveform.txt"
    if returncode == 0 and wave.exists() and "No. of Data Rows" in log:
        record["simulation_completed"] = True
        record["waveform_sha256"] = digest(wave.read_bytes())
        try:
            record.update(
                measure_waveform(
                    np.loadtxt(wave, skiprows=1),
                    3.3 if side == "gf180" else 1.8,
                    (0.1, 0.9) if side == "gf180" else (0.2, 0.8),
                )
            )
        except ValueError as error:
            record.update(waveform_gate_passed=False, waveform_error=str(error))
    write_json(folder / "measurement.json", record)
    print(
        f"{name}: completed={record['simulation_completed']}, waveform={record.get('waveform_gate_passed', False)}",
        flush=True,
    )
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("local/pad-spice"))
    parser.add_argument("--pdk-root", type=Path, default=Path("local"))
    parser.add_argument("--ngspice", type=Path, default=Path("/usr/bin/ngspice"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output, ngspice = (
        args.root.resolve(),
        args.output.resolve(),
        args.ngspice.resolve(),
    )
    sources = prepare(root)
    liberty_sources = verify(args.pdk_root, "pdk-v03/")
    repo = Path(__file__).resolve().parents[1]
    code_hashes = {
        name: digest((repo / name).read_bytes())
        for name in (
            "tools/validate_pad_spice.py",
            "tools/validation/pad_sources.py",
            "tools/validation/pad_spice.py",
            "tools/validation/sources.py",
            "src/chiplet_floorplanning/interfaces.py",
            "src/chiplet_floorplanning/liberty_checks.py",
        )
    }
    models = definitions(root, args.pdk_root / "pdk-v03")
    conversion = conversion_audit(
        (root / "gf180/bi_t.cdl").read_text(), (root / "gf180/bi_t.spice").read_text()
    )
    # The Volare file has a wrapped cell name. Compare only the four IN arcs;
    # table identity does not establish equivalence of the complete cells/PEX.
    original_arc = active_arc(
        models["sky130"]["library"],
        "sky130_ef_io__gpiov2_pad",
        "IN",
        "!IB_MODE_SEL&!VTRIP_SEL",
    )
    matched_arc = active_arc(
        root / MATCHED_LIBERTY,
        "sky130_ef_io__gpiov2_pad_wrapped",
        "IN",
        "!IB_MODE_SEL&!VTRIP_SEL",
    )
    table_identity = {}
    for kind in ("cell_rise", "cell_fall", "rise_transition", "fall_transition"):
        (a, x), (b, y) = read_table(original_arc, kind), read_table(matched_arc, kind)
        table_identity[kind] = all(
            np.array_equal(u, v) for u, v in zip(a, b)
        ) and np.array_equal(x, y)
    output.mkdir(parents=True, exist_ok=False)
    init = output / "init"
    init.mkdir()
    (init / "spinit").write_text(
        "* Isolated initialization; compatibility is an explicit command argument.\n"
    )
    configs = []
    # These are independent DC-temperature experiments, not a thermal trajectory.
    # SKY's structural failure permits a nominal diagnostic only, no temperature sweep.
    for side, temp, slew, load, step in (
        *[("gf180", t, 0.5, 6.0, 10.0) for t in (0, 25, 50, 75, 100, 125)],
        ("gf180", 25, 0.08, 6.0, 10.0),
        ("gf180", 25, 1.0, 6.0, 10.0),
        ("gf180", 25, 0.5, 12.0, 10.0),
        ("gf180", 25, 0.5, 2.0, 10.0),
        ("gf180", 25, 0.5, 6.0, 5.0),
        ("gf180", 125, 0.5, 6.0, 5.0),
        ("sky130", 25, 1.0, 0.022799, 20.0),
        ("sky130", 25, 1.0, 0.022799, 10.0),
    ):
        configs.append(
            dict(
                side=side,
                temperature_c=temp,
                input_slew_ns=slew,
                external_load_pf=load,
                max_step_ps=step,
            )
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(
            pool.map(
                lambda c: simulate(c, models, root, ngspice, output, init), configs
            )
        )
    expected_metrics = all(r.get("waveform_gate_passed", False) for r in records)
    convergence, comparisons, holdouts = {}, {}, {}
    if expected_metrics:

        def select(side, temp, slew, load, step):
            found = [
                r
                for r in records
                if (
                    r["side"],
                    r["temperature_c"],
                    r["input_slew_ns"],
                    r["external_load_pf"],
                    r["max_step_ps"],
                )
                == (side, temp, slew, load, step)
            ]
            if len(found) != 1:
                raise ValueError("missing or duplicated experiment")
            return found[0]

        for side, temp, slew, load, step in (
            ("gf180", 25, 0.5, 6, 10),
            ("gf180", 125, 0.5, 6, 10),
            ("sky130", 25, 1, 0.022799, 20),
        ):
            coarse, fine = select(side, temp, slew, load, step), select(
                side, temp, slew, load, step / 2
            )
            convergence[coarse["name"]] = differences(
                coarse["metrics"], fine["metrics"], 0.002, 0.005
            )
        for r in records:
            if r["temperature_c"] != 25 or r["max_step_ps"] != (
                10.0 if r["side"] == "gf180" else 20.0
            ):
                continue
            side, metrics = r["side"], r["metrics"]
            info = models[side]
            condition = (
                "!IE&OE&PDRV0&PDRV1&!SL"
                if side == "gf180"
                else "!IB_MODE_SEL&!VTRIP_SEL"
            )
            arc = active_arc(info["library"], info["cell"], info["output"], condition)
            load = r["external_load_pf"]
            output_pin = unique_group(
                unique_group(Path(info["library"]).read_text(), "cell", info["cell"]),
                "pin",
                info["output"],
            )
            if side == "gf180":
                pad = unique_group(
                    unique_group(
                        Path(info["library"]).read_text(), "cell", info["cell"]
                    ),
                    "pin",
                    "PAD",
                )
                self_pf = float(re.search(r"\bcapacitance\s*:\s*([\d.]+)", pad)[1])
                load += self_pf
            reference = {}
            for edge in ("rise", "fall"):
                # Measured input slews must match the declared values below;
                # exact declared values avoid endpoint roundoff in bounded lookup.
                point = (r["input_slew_ns"], load)
                reference[edge + "_delay_ns"] = lookup(
                    read_table(arc, "cell_" + edge), point
                )
                reference[edge + "_slew_ns"] = lookup(
                    read_table(arc, edge + "_transition"), point
                )
            comparisons[r["name"]] = dict(
                liberty_load_axis_pf=load,
                load_mapping=(
                    "GF STA-net convention: external C plus Liberty inout-pin C; physical self C stays in transistor circuit"
                    if side == "gf180"
                    else "external output capacitor"
                ),
                **differences(metrics, reference, 0.020, 0.10),
            )
            limit = re.search(r"\bmax_transition\s*:\s*([\d.]+)", output_pin)
            if limit:
                max_slew = float(limit[1])
                comparisons[r["name"]]["nominal_output_slew_check"] = dict(
                    max_transition_ns=max_slew,
                    measured_slews_within_limit=all(
                        metrics[e + "_slew_ns"] <= max_slew for e in ("rise", "fall")
                    ),
                    liberty_slews_within_limit=all(
                        reference[e + "_slew_ns"] <= max_slew for e in ("rise", "fall")
                    ),
                    scope="25 C output slew only; not a complete electrical qualification",
                )
        low = select("gf180", 0, 0.5, 6, 10)["metrics"]
        high = select("gf180", 125, 0.5, 6, 10)["metrics"]
        for temp in (25, 50, 75, 100):
            r = select("gf180", temp, 0.5, 6, 10)
            weight = r["temperature_c"] / 125
            predicted = {k: low[k] * (1 - weight) + high[k] * weight for k in low}
            holdouts[str(r["temperature_c"])] = differences(
                predicted, r["metrics"], 0.005, 0.02
            )
    software_checks = {
        "upstream_conversion_preserves_all_210_elements": conversion["element_count"]
        == 210,
        "all_14_simulations_completed": len(records) == 14
        and all(r["simulation_completed"] for r in records),
        "all_waveform_measurements_valid": expected_metrics,
        "input_slews_match_stimulus_convention": expected_metrics
        and all(
            abs(r["metrics"][e + "_input_slew_ns"] - r["input_slew_ns"]) < 1e-8
            for r in records
            for e in ("rise", "fall")
        ),
        "timestep_convergence": len(convergence) == 3
        and all(c["passed"] for c in convergence.values()),
        "receiver_active_tables_identical_in_spice_build": all(table_identity.values()),
    }
    gates = {
        "io_structure_has_no_empty_or_unresolved_subcircuits": all(
            m["closure"]["structural_gate_passed"] for m in models.values()
        ),
        "simulator_has_no_model_or_convergence_diagnostics": all(
            not r["diagnostics"] for r in records
        ),
        "nominal_liberty_agreement": len(comparisons) == 6
        and all(c["passed"] for c in comparisons.values()),
        "gf180_temperature_holdout_interpolation": len(holdouts) == 4
        and all(c["passed"] for c in holdouts.values()),
        "same_interface_hot_link_ready": False,
    }
    report = dict(
        software_checks_passed=all(software_checks.values()),
        software_checks=software_checks,
        qualification_gates=gates,
        models=models,
        conversion=conversion,
        records=records,
        timestep_convergence=convergence,
        nominal_liberty_comparisons=comparisons,
        gf180_temperature_holdouts=holdouts,
        same_build_receiver_table_identity=table_identity,
        source=git_revision(repo),
        source_lock=sources,
        liberty_source_hashes={
            name: value
            for name, value in liberty_sources.items()
            if name.endswith(("/gf_bi_t_tt_3v3.lib", "/sky_io_tt_1v8_3v3.lib"))
        },
        source_code_sha256=code_hashes,
        ngspice_version=subprocess.check_output(
            [str(ngspice), "--version"], text=True
        ).strip(),
        ngspice_executable_sha256=digest(ngspice.read_bytes()),
        physical_package_calibration=False,
        complete_package_signoff=False,
        scope="Transistor-model diagnostic, fixed TT/P/V. GF temperature sensitivity is conditional on source-model fidelity; not a released timing model.",
        coverage_gaps=[
            "SKY130 reachable empty pad/parasitic-diode subcircuits",
            "SKY130 original and same-build active receiver tables are identical, but no transistor/PEX equivalence proof",
            "model warnings and nominal waveform/Liberty mismatch",
            "GF load-axis convention inferred from self-capacitance offset and STA, not an original characterization deck",
            "no complete pad-temperature PVT or temperature-dependent active core arcs in this interface",
            "no measured package channel or silicon data",
        ],
    )
    write_json(output / "report.json", report)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "software_checks_passed",
                    "software_checks",
                    "qualification_gates",
                )
            },
            indent=2,
        )
    )
    if not report["software_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
