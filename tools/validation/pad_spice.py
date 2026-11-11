"""Bounded diagnostic pad decks and independent waveform measurements.

This is not a general SPICE parser, a Liberty characterizer or a qualified PHY.
The selected pad modes are shared with the existing STA prototype.
"""

from collections import Counter
from pathlib import Path
import re

import numpy as np

from chiplet_floorplanning.interfaces import GF_TX_CONTROLS, SKY_RX_CONTROLS
from chiplet_floorplanning.liberty_checks import unique_group


def logical_lines(text):
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if not lines:
                raise ValueError("orphan SPICE continuation")
            lines[-1] += " " + line[1:].strip()
        else:
            lines.append(line)
    return lines


def subcircuits(text):
    blocks, active = {}, None
    for line in logical_lines(text):
        tokens = line.split()
        directive = tokens[0].lower()
        if directive == ".subckt":
            name = tokens[1].lower()
            if active is not None or name in blocks:
                raise ValueError("nested or duplicate subcircuit")
            end = next(
                (i for i, t in enumerate(tokens) if "=" in t or t.lower() == "params:"),
                len(tokens),
            )
            blocks[name] = {"pins": tokens[2:end], "elements": []}
            active = name
        elif directive == ".ends":
            if active is None:
                raise ValueError("unmatched .ends")
            active = None
        elif active is not None and not directive.startswith("."):
            blocks[active]["elements"].append(line)
    if active is not None:
        raise ValueError("unterminated subcircuit")
    return blocks


def closure(blocks, top, external_subcircuits=()):
    """Visit IO hierarchy once per definition; external primitives stay explicit."""
    visited, empty, unresolved, primitives = set(), set(), set(), set()
    external = {name.lower() for name in external_subcircuits}

    def visit(name, stack):
        if name in stack:
            raise ValueError("recursive pad subcircuit")
        if name not in blocks:
            (primitives if name in external else unresolved).add(name)
            return
        if name in visited:
            return
        visited.add(name)
        if not blocks[name]["elements"]:
            empty.add(name)
        for line in blocks[name]["elements"]:
            if line[0].lower() == "x":
                tokens = line.lower().split()
                end = next(
                    (i for i, t in enumerate(tokens) if "=" in t or t == "params:"),
                    len(tokens),
                )
                child = tokens[end - 1]
                if child in blocks and end - 2 != len(blocks[child]["pins"]):
                    raise ValueError(f"subcircuit port count mismatch: {child}")
                visit(child, stack | {name})

    visit(top.lower(), set())
    return dict(
        visited_io_subcircuits=sorted(visited),
        empty_subcircuits=sorted(empty),
        unresolved_subcircuits=sorted(unresolved),
        declared_external_primitives=sorted(primitives),
        structural_gate_passed=not empty and not unresolved,
        scope="IO X-instance hierarchy only; primitive behavior and active model sections require simulator checks",
    )


def conversion_audit(cdl, spice):
    """Require the exact allowed upstream syntax edits, preserving every value."""
    expected = []
    for original in cdl.splitlines():
        line = re.sub(r"^[RCM]", "X", original, flags=re.I)
        line = re.sub(r" \$\[", " ", line, flags=re.I)
        line = re.sub(r"\] ", " ", line, flags=re.I)
        line = re.sub(r"\$SUB=", "", line, flags=re.I)
        if original[:1].upper() == "R":
            line = re.sub(r"\$W", "r_width", line, flags=re.I)
            line = re.sub(r"\$L", "r_length", line, flags=re.I)
        if original[:1].upper() == "C":
            line = re.sub("w=", "c_width=", line, flags=re.I)
            line = re.sub("l=", "c_length=", line, flags=re.I)
        expected.append(line.replace("AREA", "area").replace("PJ", "pj"))
    if logical_lines("\n".join(expected)) != logical_lines(spice):
        raise ValueError("CDL conversion changed topology or unsupported parameters")
    before = [s for s in logical_lines(cdl) if not s.startswith(".")]
    after = [s for s in logical_lines(spice) if not s.startswith(".")]
    if len(before) != len(after):
        raise ValueError("CDL conversion lost elements")
    return dict(
        element_count=len(after),
        original_types=dict(Counter(s[0] for s in before)),
        converted_types=dict(Counter(s[0] for s in after)),
        allowed_syntax_only=True,
    )


def crossing_ns(time_ns, voltage_v, threshold_v, rising):
    delta = voltage_v - threshold_v
    mask = (
        ((delta[:-1] < 0) & (delta[1:] >= 0))
        if rising
        else ((delta[:-1] > 0) & (delta[1:] <= 0))
    )
    indices = np.flatnonzero(mask)
    if len(indices) != 1:
        raise ValueError(f"expected one threshold crossing, found {len(indices)}")
    i = indices[0]
    return float(
        time_ns[i]
        + (time_ns[i + 1] - time_ns[i]) * (-delta[i]) / (delta[i + 1] - delta[i])
    )


def measure_waveform(data, output_voltage_v, slew_fraction):
    """Measure noninverting 10/40 ns stimulus edges in a 70 ns transient."""
    if (
        data.ndim != 2
        or data.shape[1] != 3
        or len(data) < 20
        or not np.all(np.isfinite(data))
    ):
        raise ValueError("invalid waveform samples")
    time_ns, vin, vout = data.T.copy()
    time_ns *= 1e9
    if np.any(np.diff(time_ns) <= 0) or time_ns[0] > 0.001 or time_ns[-1] < 69.99:
        raise ValueError("incomplete or nonmonotonic waveform times")
    rails = {}
    for name, lo, hi, expected in (
        ("initial_low", 5, 9, 0),
        ("high", 35, 39, output_voltage_v),
        ("final_low", 65, 69, 0),
    ):
        samples = vout[(time_ns >= lo) & (time_ns <= hi)]
        if not len(samples):
            raise ValueError("missing settled-rail samples")
        rails[name + "_max_error_v"] = float(np.max(np.abs(samples - expected)))
    metrics = {}
    lower, upper = slew_fraction
    for name, lo, hi, rising in (("rise", 9, 39, True), ("fall", 39, 69, False)):
        mask = (time_ns >= lo) & (time_ns <= hi)
        t, a, b = time_ns[mask], vin[mask], vout[mask]
        ti = crossing_ns(t, a, 3.3 * 0.5, rising)
        to = crossing_ns(t, b, output_voltage_v * 0.5, rising)
        tlo = crossing_ns(t, b, output_voltage_v * lower, rising)
        thi = crossing_ns(t, b, output_voltage_v * upper, rising)
        metrics[name + "_delay_ns"] = to - ti
        metrics[name + "_slew_ns"] = (thi - tlo) if rising else (tlo - thi)
        metrics[name + "_input_slew_ns"] = abs(
            crossing_ns(t, a, 3.3 * upper, rising)
            - crossing_ns(t, a, 3.3 * lower, rising)
        )
    return dict(
        metrics=metrics,
        output_min_v=float(np.min(vout)),
        output_max_v=float(np.max(vout)),
        settled_rail_errors=rails,
        waveform_gate_passed=all(e <= 0.05 * output_voltage_v for e in rails.values())
        and all(value > 0 for key, value in metrics.items() if "slew" in key),
        samples=len(data),
        measured_crossings="one per edge per required threshold",
    )


def pin_connections(side, pins, liberty):
    """No default-to-ground for unknown pins; map logical highs to Liberty rails."""
    if side == "gf180":
        supplies = {"VDD": "v33", "DVDD": "v33", "VSS": "0", "DVSS": "0"}
        controls, io = GF_TX_CONTROLS, {"A": "vin", "PAD": "vout", "Y": "nc_y"}
        cell = "gf180mcu_fd_io__bi_t"
    elif side == "sky130":
        supplies = {p: "v33" for p in ("VDDIO", "VDDIO_Q", "VDDA", "VSWITCH")}
        supplies.update({p: "v18" for p in ("VCCD", "VCCHIB")})
        supplies.update({p: "0" for p in ("VSSA", "VSSIO", "VSSD", "VSSIO_Q")})
        controls = {**SKY_RX_CONTROLS, "DM[2]": 0, "DM[1]": 0, "DM[0]": 1}
        io = {"PAD": "vin", "IN": "vout"}
        io.update(
            {
                p: "nc_" + p.lower()
                for p in (
                    "IN_H",
                    "PAD_A_NOESD_H",
                    "PAD_A_ESD_0_H",
                    "PAD_A_ESD_1_H",
                    "TIE_HI_ESD",
                    "TIE_LO_ESD",
                    "AMUXBUS_A",
                    "AMUXBUS_B",
                )
            }
        )
        cell = "sky130_ef_io__gpiov2_pad"
    else:
        raise ValueError("unsupported pad side")
    if set(pins) != supplies.keys() | controls.keys() | io.keys():
        raise ValueError("pad wrapper pins differ from the declared interface")
    body = unique_group(liberty, "cell", cell)
    mapping, domains = {**supplies, **io}, {}
    for pin, value in controls.items():
        group = unique_group(body, "pin", pin)
        attribute = "input_signal_level" if side == "gf180" else "related_power_pin"
        match = re.search(r"\b" + attribute + r'\s*:\s*"?(\w+)', group)
        if not match or match[1] not in supplies:
            raise ValueError(f"unknown Liberty control supply for {pin}")
        domains[pin] = match[1]
        mapping[pin] = supplies[match[1]] if value else "0"
    return mapping, domains


def deck(
    root,
    side,
    mapping,
    pins,
    temperature_c,
    input_slew_ns,
    external_load_pf,
    max_step_ps,
):
    values = [temperature_c, input_slew_ns, external_load_pf, max_step_ps]
    if (
        not np.all(np.isfinite(values))
        or not 0 <= temperature_c <= 125
        or input_slew_ns <= 0
        or external_load_pf <= 0
        or max_step_ps <= 0
    ):
        raise ValueError("invalid bounded pad experiment parameters")
    root = Path(root).resolve()
    lines = [f"Diagnostic {side} pad TT {temperature_c} C; not qualified timing"]
    if side == "gf180":
        folder = root / "gf180"
        lines += [f'.include "{folder}/design.ngspice"']
        lines += [
            f'.lib "{folder}/sm141064.ngspice" {corner}'
            for corner in ("typical", "res_typical", "moscap_typical", "diode_typical")
        ]
        lines += [
            ".param sw_stat_global=0 sw_stat_mismatch=0",
            f'.include "{folder}/bi_t.spice"',
        ]
        cell, span = "gf180mcu_fd_io__bi_t", 0.8
    elif side == "sky130":
        folder = root / "sky130A"
        lines += [f'.lib "{folder}/libs.tech/ngspice/sky130.lib.spice" tt']
        lines += [
            f'.include "{folder}/libs.ref/sky130_fd_io/spice/{f}.spice"'
            for f in ("sky130_fd_io", "sky130_ef_io")
        ]
        cell, span = "sky130_ef_io__gpiov2_pad", 0.6
    else:
        raise ValueError("unsupported pad side")
    ramp = input_slew_ns / span
    if ramp >= 20 or max_step_ps / 1000 > ramp / 4:
        raise ValueError("stimulus exceeds plateau or timestep bounds")
    lines += [
        "V33 v33 0 3.3",
        "V18 v18 0 1.8",
        f"VIN vin 0 PWL(0 0 10n 0 {10+ramp:.12g}n 3.3 40n 3.3 {40+ramp:.12g}n 0 70n 0)",
        "Xpad " + " ".join(mapping[p] for p in pins) + " " + cell,
        f"Cload vout 0 {external_load_pf:.12g}p",
        f".temp {temperature_c}",
        ".options reltol=1e-5 abstol=1e-12 vntol=1e-7",
        ".control",
        "set numdgt=15",
        "set wr_singlescale",
        "set wr_vecnames",
        f"tran {max_step_ps}p 70n 0 {max_step_ps}p",
        "wrdata waveform.txt v(vin) v(vout)",
        "quit",
        ".endc",
        ".end",
    ]
    return "\n".join(lines) + "\n"


def log_diagnostics(log):
    lines = [s.strip() for s in log.splitlines()]
    return [
        s
        for s in lines
        if re.search(r"warning:|error|unrecognized|ignored|fatal|failed", s, re.I)
    ]


def differences(candidate, reference, abs_ns, relative):
    result = {}
    for metric in ("rise_delay_ns", "fall_delay_ns", "rise_slew_ns", "fall_slew_ns"):
        a, b = candidate[metric], reference[metric]
        if not np.isfinite(a) or not np.isfinite(b):
            raise ValueError("nonfinite metric")
        error = abs(a - b)
        limit = max(abs_ns, relative * abs(b))
        result[metric] = dict(
            error_ns=error,
            reference_ns=b,
            candidate_ns=a,
            limit_ns=limit,
            passed=error <= limit,
        )
    return dict(passed=all(item["passed"] for item in result.values()), metrics=result)
