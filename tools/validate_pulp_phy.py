"""Self-checking transport through pinned unchanged serial_link SDR PHY RTL."""

import argparse
from chiplet_floorplanning.cli import source_revision
import json
import os
import resource
from pathlib import Path
import subprocess
from validation.sources import verify, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("local"))
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = args.root.resolve() / "open-cases"
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    hashes = {}
    for name in ("pulp", "common_cells", "tech_cells_generic"):
        hashes.update(verify(args.root, "open-cases/" + name + "/"))
    src = [
        root / "common_cells/src" / name
        for name in (
            "cc_binary_to_gray.sv",
            "cc_gray_to_binary.sv",
            "cc_spill_register_flushable.sv",
            "cc_spill_register.sv",
            "cc_cdc_fifo_gray.sv",
        )
    ]
    src += [
        root / "tech_cells_generic/src/rtl/tc_sync.sv",
        root / "tech_cells_generic/src/rtl/tc_clk.sv",
        root / "pulp/src/slink_phys_layer.sv",
        Path("tests/rtl/slink_phy_tb.sv").resolve(),
    ]
    cases = []
    for name, width, divider, delay, negative in [
        ("sdr_1", 1, 8, 2, False),
        ("sdr_8", 8, 12, 2, False),
        ("late_data", 8, 8, 90, True),
    ]:
        out = args.output / name
        out.mkdir()
        command = [
            args.verilator,
            "--binary",
            "--timing",
            "--assert",
            "-Wno-TIMESCALEMOD",
            "--top-module",
            "slink_phy_tb",
            "-j",
            "2",
            "--Mdir",
            str((out / "obj").resolve()),
            "-I" + str(root / "common_cells/include"),
            "-GWidth=" + str(width),
            "-GDivider=" + str(divider),
            "-GDataDelayNs=" + str(delay),
            *map(str, src),
        ]
        build = subprocess.run(command, capture_output=True, text=True, timeout=180)
        (out / "build.log").write_text(build.stdout + build.stderr)
        if build.returncode:
            raise RuntimeError(f"RTL compile failed: {out}/build.log")
        run = subprocess.run(
            [str((out / "obj/Vslink_phy_tb").resolve())],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "OMP_NUM_THREADS": "1"},
        )
        log = run.stdout + run.stderr
        (out / "simulation.log").write_text(log)
        write_json(out / "command.json", command)
        passed = (
            (run.returncode != 0 and "DATA_MISMATCH" in log)
            if negative
            else (
                run.returncode == 0
                and f"PHY_PASS words=128 width={width} divider={divider}" in log
            )
        )
        row = dict(
            name=name,
            width_bits=width,
            divider=divider,
            tx_clock_period_ns=10,
            rx_clock_period_ns=13,
            data_channel_delay_ns=delay,
            clock_channel_delay_ns=2,
            negative_control=negative,
            passed=passed,
            simulator_returncode=run.returncode,
            requested_words=128,
            received_words=128 if not negative and passed else None,
            expected_failure="DATA_MISMATCH" if negative else None,
        )
        cases.append(row)
        print(row, flush=True)
    report = dict(
        source_revision=source_revision(),
        passed=all(r["passed"] for r in cases),
        cases=cases,
        source_hashes=hashes,
        simulator=subprocess.check_output(
            [args.verilator, "--version"], text=True
        ).strip(),
        scope="SDR PHY transport, idle and bounded backpressure; ideal digital channel",
        not_validated=[
            "AXI protocol",
            "serializer",
            "DDR mode",
            "PDK mapped implementation",
            "analog metastability",
            "physical link",
        ],
        complete_package_signoff=False,
    )
    write_json(args.output / "report.json", report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
