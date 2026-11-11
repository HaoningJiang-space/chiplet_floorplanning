"""Strict extraction of the pinned OpenSTA full-clock report; no oracle math."""

import re

NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def extract(log):
    if re.search(r"(?mi)^(?:Error|Warning):|invalid command name", log):
        raise ValueError("STA diagnostic or unconstrained endpoint")
    if "ORACLE_CHECKS_BEGIN" not in log or "ORACLE_CHECKS_END" not in log:
        raise ValueError("missing constraint/electrical check block")
    checks = log.split("ORACLE_CHECKS_BEGIN", 1)[1].split("ORACLE_CHECKS_END", 1)[0]
    if "VIOLATED" in checks:
        raise ValueError("electrical constraint violation")
    if not re.search(r"(?m)^capture\s+.*\(generated\)$", log):
        raise ValueError("capture generated clock missing")
    blocks = re.findall(r"ORACLE_BEGIN (\w+)\n(.*?)ORACLE_END \1", log, re.S)
    expected_keys = {f"{check}_{edge}" for check in ("setup", "hold") for edge in ("rise", "fall")}
    if len(blocks) != 4 or {key for key, _ in blocks} != expected_keys:
        raise ValueError("incomplete or duplicate path reports")
    result = {}
    for key, block in blocks:
        check, transition = key.split("_")
        for label, name, clock in (("Startpoint", "tx_reg", "launch"),
                                   ("Endpoint", "rx_reg", "capture")):
            required = f"{label}: {name} (rising edge-triggered flip-flop clocked by {clock})"
            if block.count(required) != 1:
                raise ValueError(f"{key}: wrong endpoint, clock or FF polarity")
        if f"Path Type: {'max' if check == 'setup' else 'min'}" not in block:
            raise ValueError(f"{key}: wrong min/max analysis")

        def event(name):
            rows = re.findall(rf"(?m)^\s*{NUMBER}\s+({NUMBER})\s+clock {name} \(rise edge\)$", block)
            if len(rows) != 1:
                raise ValueError(f"{key}: missing {name} event")
            return float(rows[0])

        def time_line(label):
            rows = re.findall(rf"(?m)^\s*({NUMBER})\s+{label}$", block)
            if not rows:
                raise ValueError(f"{key}: missing {label}")
            return float(rows[0])

        def pin(name, edge):
            rows = re.findall(rf"(?m)^\s*([\d.eE+\-\s]+?)\s+([\^v])\s+{re.escape(name)} \([^)]+\)$", block)
            if len(rows) != 1 or rows[0][1] != edge:
                raise ValueError(f"{key}: wrong/missing transition at {name}")
            values = [float(v) for v in re.findall(NUMBER, rows[0][0])]
            if len(values) not in (3, 4):
                raise ValueError(f"{key}: malformed pin fields at {name}")
            return dict(time_ns=values[-1], delay_ns=values[-2], slew_ns=values[-3],
                        cap_pf=values[-4] if len(values) == 4 else None)

        edge = "^" if transition == "rise" else "v"
        pins = {name: pin(name, direction) for name, direction in (
            ("tx_reg/CK", "^"), ("tx_reg/Q", edge), ("tx_data/Y", edge),
            ("rx_reg/D", edge), ("tx_clock/Y", "v"),
            ("rx_clock/Y", "^"), ("rx_reg/CK", "^"))}
        result[key] = dict(
            launch_edge_ns=event("launch"), capture_edge_ns=event("capture"),
            data_arrival_ns=time_line("data arrival time"),
            capture_arrival_ns=pins["rx_reg/CK"]["time_ns"],
            required_ns=time_line("data required time"),
            slack_ns=time_line(r"slack \((?:MET|VIOLATED)\)"), pins=pins)
    return result


def compare_builds(cases, reference, tolerance_ns):
    """Compare complete reported path fields across builds, with frozen inputs."""
    if cases.keys() != reference.keys():
        raise ValueError("cross-build scenario coverage differs")
    errors_ns, errors_pf = [], []

    def visit(actual, expected, key):
        if isinstance(expected, dict):
            if not isinstance(actual, dict) or actual.keys() != expected.keys():
                raise ValueError("cross-build field coverage differs: " + key)
            for name in expected:
                visit(actual[name], expected[name], key + "." + name)
        elif expected is None:
            if actual is not None:
                raise ValueError("cross-build optional field differs: " + key)
        else:
            error = abs(actual - expected)
            cap = key.endswith("cap_pf")
            (errors_pf if cap else errors_ns).append(error)
            if error > (1e-6 if cap else tolerance_ns):
                raise ValueError(f"cross-build mismatch: {key} = {error}")

    for name, case in cases.items():
        if case["input_sha256"] != reference[name]["input_sha256"]:
            raise ValueError("cross-build inputs differ: " + name)
        visit(case["observed"], reference[name]["observed"], name)
    return dict(passed=True, compared_fields=len(errors_ns) + len(errors_pf),
                max_time_difference_ns=max(errors_ns), max_cap_difference_pf=max(errors_pf))
