"""Real-library contract checks, explicitly separate from a physical delay oracle.

Receiver constraints are independently interpolated. Propagation accounting uses
STA increments, so agreement there is not independent circuit/RC validation.
"""

from functools import lru_cache
import hashlib
from pathlib import Path
import re

from chiplet_floorplanning.liberty_checks import active_arc, groups, lookup, read_table

NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
TOLERANCE_NS = 1e-5


def unique_group(text, kind, name):
    """Locate the exact header before scanning its body, avoiding unrelated cells."""
    pattern = r'\b' + re.escape(kind) + r'\s*\(\s*"?' + re.escape(name) + r'"?\s*\)\s*\{'
    headers = list(re.finditer(pattern, text))
    if len(headers) != 1:
        raise ValueError(f"missing or ambiguous Liberty {kind} {name}")
    return next(groups(text[headers[0].start():], kind))[1]


def attribute(text, name):
    match = re.search(r'\b' + name + r'\s*:\s*"?([^";]+)"?\s*;', text)
    if not match:
        raise ValueError("missing Liberty attribute: " + name)
    return match[1].strip()


@lru_cache(maxsize=64)
def receiver_tables(path, cell):
    text = Path(path).read_text()
    body = unique_group(text, "cell", cell)
    ff = list(groups(body, "ff"))
    if len(ff) != 1 or attribute(ff[0][1], "clocked_on") != "CLK":
        raise ValueError("receiver must be a positive-edge CLK flip-flop")
    pin = unique_group(body, "pin", "D")
    result = {}
    for check in ("setup", "hold"):
        arcs = [arc for _, arc in groups(pin, "timing")
                if attribute(arc, "timing_type") == check + "_rising"
                and attribute(arc, "related_pin") == "CLK"]
        if len(arcs) != 1 or re.search(r"\bwhen\s*:", arcs[0]):
            raise ValueError("ambiguous or conditional receiver constraint")
        for edge in ("rise", "fall"):
            kind = edge + "_constraint"
            template_name = list(groups(arcs[0], kind))[0][0]
            template = unique_group(text, "lu_table_template", template_name)
            variables = [attribute(template, f"variable_{i}") for i in (1, 2)]
            if set(variables) != {"related_pin_transition", "constrained_pin_transition"}:
                raise ValueError("unsupported receiver constraint axes")
            result[f"{check}_{edge}"] = (read_table(arcs[0], kind), variables)
    return result


def query_constraint(path, cell, check, edge, data_slew_ns, clock_slew_ns):
    table, variables = receiver_tables(str(Path(path).resolve()), cell)[f"{check}_{edge}"]
    values = {"related_pin_transition": clock_slew_ns,
              "constrained_pin_transition": data_slew_ns}
    point = [values[v] for v in variables]
    inside = all(axis[0] <= p <= axis[-1] for axis, p in zip(table[0], point))
    return dict(value_ns=lookup(table, point, bounded=False), inside_table_domain=bool(inside),
                axis_variables=variables, query_ns=point,
                axis_bounds_ns=[[float(a[0]), float(a[-1])] for a in table[0]])


def library_for_receiver(run_folder):
    folder = Path(run_folder)
    netlist = (folder / "lane.v").read_text()
    match = re.search(r"(?m)^\s*(\w+)\s+rx_reg\s*\(", netlist)
    if not match:
        raise ValueError("missing receiver instance in netlist")
    cell = match[1]
    paths = re.findall(r"(?m)^read_liberty\s+\{([^}]+)\}", (folder / "run.tcl").read_text())
    matches = [Path(p) for p in paths if re.search(
        r'\bcell\s*\(\s*"?' + re.escape(cell) + r'"?\s*\)', Path(p).read_text())]
    if len(matches) != 1:
        raise ValueError("receiver cell is missing or ambiguous across loaded libraries")
    return matches[0], cell


def core_arcs(pads):
    return ([("tx_reg", "CLK", "Q"), ("tx_data", "I", "Z"), ("tx_clock", "I", "Z"),
             ("rx_data", "A", "X"), ("rx_clock", "A", "Y")] if pads else
            [("tx_reg", "CLK", "Q"), ("tx_data", "A", "X"), ("tx_clock", "A", "X"),
             ("rx_clock", "I", "ZN")])


def diagnostics(pads=False):
    text = 'puts "BRIDGE_CHECKS_BEGIN"\ncheck_setup -verbose\nreport_clock_properties [all_clocks]\nputs "BRIDGE_CHECKS_END"\n'
    for check, mode in (("setup", "max"), ("hold", "min")):
        for edge in ("rise", "fall"):
            key = check + "_" + edge
            text += f'''puts "BRIDGE_BEGIN {key}"
report_checks -from [get_cells tx_reg] -{edge}_to [get_pins rx_reg/D] -path_delay {mode} -format full_clock_expanded -fields {{slew cap input_pin nets fanout}} -digits 9
puts "BRIDGE_END {key}"
'''
    for instance, source, target in core_arcs(pads):
        for mode in ("max", "min"):
            text += (f'puts "BRIDGE_ARC_BEGIN {instance} {mode}"\n'
                     f'report_dcalc -from {instance}/{source} -to {instance}/{target} -{mode} -digits 9\n'
                     f'puts "BRIDGE_ARC_END {instance} {mode}"\n')
    return text + "exit\n"


@lru_cache(maxsize=32)
def library_text(path):
    return Path(path).read_text()


@lru_cache(maxsize=128)
def propagation_tables(paths, cell, source, target):
    owners = [p for p in paths if re.search(r'\bcell\s*\(\s*"?' + re.escape(cell)
                                          + r'"?\s*\)', library_text(p))]
    if len(owners) != 1:
        raise ValueError("ambiguous propagation cell library")
    text = library_text(owners[0])
    cell_body = unique_group(text, "cell", cell)
    pin = unique_group(cell_body, "pin", target)
    arcs = [a for _, a in groups(pin, "timing") if attribute(a, "related_pin") == source]
    if len(arcs) != 1 or re.search(r"\bwhen\s*:", arcs[0]):
        raise ValueError("conditional or ambiguous core propagation arc")
    tables = {}
    for kind in ("cell_rise", "cell_fall", "rise_transition", "fall_transition"):
        template_name = list(groups(arcs[0], kind))[0][0]
        template = unique_group(text, "lu_table_template", template_name)
        variables = [attribute(template, f"variable_{i}") for i in (1, 2)]
        if variables != ["input_net_transition", "total_output_net_capacitance"]:
            raise ValueError("unsupported core propagation axes")
        tables[kind] = read_table(arcs[0], kind)
    tables["identity"] = dict(related_pin=attribute(arcs[0], "related_pin"),
                              timing_sense=(attribute(arcs[0], "timing_sense") if re.search(r"\btiming_sense\s*:", arcs[0]) else None),
                              timing_type=(attribute(arcs[0], "timing_type") if re.search(r"\btiming_type\s*:", arcs[0]) else "combinational"),
                              when=None)
    if source == "CLK":
        ff = list(groups(cell_body, "ff"))
        if len(ff) != 1 or attribute(ff[0][1], "clocked_on") != "CLK":
            raise ValueError("source FF must use a positive-edge CLK")
    return tables


def audit_core_tables(log, run_folder, bridge, pads):
    """Conditional NLDM validation at STA slew/Ceff; not an independent Ceff solver."""
    folder = Path(run_folder)
    paths = tuple(re.findall(r"(?m)^read_liberty\s+\{([^}]+)\}", (folder / "run.tcl").read_text()))
    netlist = (folder / "lane.v").read_text()
    records = []
    for instance, source, target in core_arcs(pads):
        cell = re.search(r"(?m)^\s*(\w+)\s+" + instance + r"\s*\(", netlist)[1]
        tables = propagation_tables(paths, cell, source, target)
        identity = tables["identity"]
        expected_sense = "non_unate" if instance == "tx_reg" else ("negative_unate" if instance == "rx_clock" else "positive_unate")
        expected_type = "rising_edge" if instance == "tx_reg" else "combinational"
        sense_ok = (identity["timing_sense"] in (None, "non_unate") if instance == "tx_reg"
                    else identity["timing_sense"] == expected_sense)
        if not sense_ok or identity["timing_type"] != expected_type:
            raise ValueError("wrong core arc identity: " + instance)
        for mode in ("max", "min"):
            start, end = f"BRIDGE_ARC_BEGIN {instance} {mode}", f"BRIDGE_ARC_END {instance} {mode}"
            if log.count(start) != 1 or log.count(end) != 1:
                raise ValueError("missing core NLDM diagnostic")
            section = log.split(start, 1)[1].split(end, 1)[0]
            for edge, symbol in (("rise", "^"), ("fall", "v")):
                pattern = re.escape(source) + r" ([\^v]) -> " + re.escape(target + " " + symbol) + r"\n(.*?)(?=\.{10}|\Z)"
                found = list(re.finditer(pattern, section, re.S))
                if len(found) != 1:
                    raise ValueError("ambiguous core NLDM edge calculation")
                body = found[0][2]

                def number(name):
                    m = re.search(re.escape(name) + rf" = ({NUMBER})", body)
                    if not m:
                        raise ValueError("incomplete core NLDM diagnostic: " + name)
                    return float(m[1])

                point = [number("input_net_transition"), number("total_output_net_capacitance")]
                domain, errors = {}, []
                for kind, observed in (("cell_" + edge, number("Delay")),
                                        (edge + "_transition", number("Slew"))):
                    table = tables[kind]
                    domain[kind] = bool(all(a[0] <= p <= a[-1] for p, a in zip(point, table[0])))
                    errors.append(abs(lookup(table, point, bounded=False) - observed))
                if max(errors) > TOLERANCE_NS:
                    raise ValueError(f"core source-table mismatch: {instance} {mode} {edge}: {max(errors)}")
                records.append(dict(instance=instance, cell=cell, mode=mode, edge=edge,
                                    arc_identity=identity,
                                    input_edge=found[0][1], query_slew_ns=point[0], query_ceff_pf=point[1],
                                    inside_table_domain=all(domain.values()), domain=domain,
                                    delay_ns=number("Delay"), nldm_slew_ns=number("Slew"),
                                    max_abs_error_ns=max(errors), used_in_paths=[]))
    for key, path in bridge["paths"].items():
        check = key.split("_")[0]
        for lane in ("data", "clock"):
            mode = ("max" if check == "setup" else "min") if lane == "data" else ("min" if check == "setup" else "max")
            for instance, source, target in core_arcs(pads):
                pins = [p for p in path[lane + "_path"] if p["pin"] == instance + "/" + target]
                if not pins:
                    continue
                pin = pins[0]
                edge = "rise" if pin["edge"] == "^" else "fall"
                record = next(r for r in records if (r["instance"], r["mode"], r["edge"]) == (instance, mode, edge))
                source_pin = next(p for p in path[lane + "_path"] if p["pin"] == instance + "/" + source)
                if record["input_edge"] != source_pin["edge"]:
                    raise ValueError("core diagnostic uses a different input edge")
                if abs(record["delay_ns"] - pin["increment_ns"]) > TOLERANCE_NS:
                    raise ValueError(f"path does not match core NLDM query: {key} {instance}")
                record["used_in_paths"].append(key)
    return records


def audit_pad_path_identity(bridge, records, sky_path, gf_path):
    """Bind the fixed GPIO mode's NLDM records to all four expanded paths."""
    definitions = {
        "tx": (gf_path, "gf180mcu_fd_io__bi_t", "A", "PAD", "!IE&OE&PDRV0&PDRV1&!SL"),
        "rx": (sky_path, "sky130_ef_io__gpiov2_pad", "PAD", "IN", "!IB_MODE_SEL&!VTRIP_SEL")}
    for side, (path, cell, source, target, condition) in definitions.items():
        arc = active_arc(path, cell, target, condition)
        if attribute(arc, "related_pin") != source or attribute(arc, "timing_sense") != "positive_unate":
            raise ValueError("wrong active GPIO arc identity")
        for key, data in bridge["paths"].items():
            for lane in ("data", "clock"):
                mode = ("max" if key.startswith("setup") else "min") if lane == "data" else ("min" if key.startswith("setup") else "max")
                instance = f"{side}_{lane}_pad"
                pin = next(p for p in data[lane + "_path"] if p["pin"] == instance + "/" + target)
                edge = "rise" if pin["edge"] == "^" else "fall"
                record = next(r for r in records if (r["instance"], r["mode"], r["edge"]) == (instance, mode, edge))
                if abs(record["delay_ns"] - pin["increment_ns"]) > TOLERANCE_NS:
                    raise ValueError("GPIO path does not use selected source mode")
                record.setdefault("bridge_paths", []).append(key)


def sequences(pads):
    if pads:
        data = ["clk", "tx_reg/CLK", "tx_reg/Q", "tx_data/I", "tx_data/Z", "tx_data_pad/A",
                "tx_data_pad/PAD", "rx_data_pad/PAD", "rx_data_pad/IN", "rx_data/A", "rx_data/X", "rx_reg/D"]
        clock = ["clk", "tx_clock/I", "tx_clock/Z", "tx_clock_pad/A", "tx_clock_pad/PAD",
                 "rx_clock_pad/PAD", "rx_clock_pad/IN", "rx_clock/A", "rx_clock/Y", "rx_reg/CLK"]
    else:
        data = ["clk", "tx_reg/CLK", "tx_reg/Q", "tx_data/A", "tx_data/X", "rx_reg/D"]
        clock = ["clk", "tx_clock/A", "tx_clock/X", "rx_clock/I", "rx_clock/ZN", "rx_reg/CLK"]
    return data, clock


def audit(log, receiver_library, receiver_cell, period_ns=20.0, duty=0.5,
          setup_uncertainty_ns=0.0, hold_uncertainty_ns=0.0, pads=False):
    if re.search(r"(?m)^(?:Error|Warning):|invalid command name", log):
        raise ValueError("STA diagnostics or unconstrained endpoints")
    if log.count("BRIDGE_CHECKS_BEGIN") != 1 or log.count("BRIDGE_CHECKS_END") != 1:
        raise ValueError("missing constraint/clock coverage checks")
    if not re.search(r"(?m)^capture\s+.*\(generated\)$", log):
        raise ValueError("missing generated capture clock")
    blocks = re.findall(r"BRIDGE_BEGIN (\w+)\n(.*?)BRIDGE_END \1", log, re.S)
    expected_keys = {c + "_" + e for c in ("setup", "hold") for e in ("rise", "fall")}
    if len(blocks) != 4 or {k for k, _ in blocks} != expected_keys:
        raise ValueError("incomplete four-path coverage")
    expected_data, expected_clock = sequences(pads)
    result = {}
    for key, block in blocks:
        check, edge = key.split("_")
        errors = {}

        def close(name, observed, expected):
            errors[name] = abs(observed - expected)
            if errors[name] > TOLERANCE_NS:
                raise ValueError(f"{key}: {name} mismatch {observed} versus {expected}")

        for label, instance, clock in (("Startpoint", "tx_reg", "launch"), ("Endpoint", "rx_reg", "capture")):
            if block.count(f"{label}: {instance} (rising edge-triggered flip-flop clocked by {clock})") != 1:
                raise ValueError(f"{key}: wrong endpoint, polarity or clock")
        if f"Path Type: {'max' if check == 'setup' else 'min'}" not in block:
            raise ValueError(f"{key}: wrong min/max path type")

        def value(label, last_column=True):
            rows = re.findall(rf"(?m)^\s*({NUMBER}(?:[ \t]+{NUMBER})*)\s+{label}$", block)
            if not rows:
                raise ValueError(f"{key}: missing {label}")
            numbers = [float(v) for v in re.findall(NUMBER, rows[0])]
            return numbers[-1] if last_column else numbers[0]

        launch = value(r"clock launch \(rise edge\)")
        capture = value(r"clock capture \(rise edge\)")
        close("launch_edge_ns", launch, 0 if check == "setup" else period_ns)
        close("capture_edge_ns", capture, period_ns * duty)
        split = block.index("clock capture (rise edge)")

        def pins(section):
            records = []
            for row in re.finditer(r"(?m)^[ \t]*([^\r\n]*?)[ \t]+([\^v])[ \t]+(\S+)[ \t]+\(([^)]+)\)$", section):
                if row[4] == "net":
                    continue
                numbers = [float(v) for v in re.findall(NUMBER, row[1])]
                if len(numbers) != 3:
                    raise ValueError(f"{key}: unexpected pin column format")
                records.append(dict(pin=row[3], edge=row[2], cell=row[4], slew_ns=numbers[0],
                                    increment_ns=numbers[1], arrival_ns=numbers[2]))
            return records

        data, clock = pins(block[:split]), pins(block[split:])
        for label, records, names, start in (("data", data, expected_data, launch),
                                            ("clock", clock, expected_clock, capture)):
            if [r["pin"] for r in records] != names:
                raise ValueError(f"{key}: wrong {label} path topology")
            time = start
            for i, record in enumerate(records):
                expected_edge = ("^" if i < 2 else ("^" if edge == "rise" else "v")) if label == "data" else ("^" if i >= len(records)-2 else "v")
                if record["edge"] != expected_edge:
                    raise ValueError(f"{key}: wrong transition at {record['pin']}")
                time += record["increment_ns"]
                close(label + "." + record["pin"] + ".arrival_ns", record["arrival_ns"], time)
        if data[-1]["cell"] != receiver_cell or clock[-1]["cell"] != receiver_cell:
            raise ValueError("reported receiver differs from loaded-library contract")
        constraint = query_constraint(receiver_library, receiver_cell, check, edge,
                                      data[-1]["slew_ns"], clock[-1]["slew_ns"])
        reported_constraint = value("library " + check + " time", False)
        close("receiver_constraint_ns", reported_constraint,
              -constraint["value_ns"] if check == "setup" else constraint["value_ns"])
        close("clock_reconvergence_pessimism_ns", value("clock reconvergence pessimism", False), 0.0)
        uncertainty = setup_uncertainty_ns if check == "setup" else hold_uncertainty_ns
        actual_uncertainty = value("clock uncertainty", False) if "clock uncertainty" in block else 0.0
        close("uncertainty_ns", actual_uncertainty, -uncertainty if check == "setup" else uncertainty)
        arrival = launch + sum(r["increment_ns"] for r in data)
        clock_arrival = capture + sum(r["increment_ns"] for r in clock)
        required = clock_arrival + (-constraint["value_ns"] - uncertainty if check == "setup"
                                    else constraint["value_ns"] + uncertainty)
        slack = required - arrival if check == "setup" else arrival - required
        close("data_arrival_ns", value("data arrival time"), arrival)
        close("required_time_ns", value("data required time"), required)
        close("slack_ns", value(r"slack \((?:MET|VIOLATED)\)"), slack)
        result[key] = dict(launch_edge_ns=launch, capture_edge_ns=capture,
                           data_arrival_ns=arrival, clock_arrival_ns=clock_arrival,
                           required_ns=required, slack_ns=slack, uncertainty_ns=uncertainty,
                           receiver_constraint=constraint, data_path=data, clock_path=clock,
                           max_abs_error_ns=max(errors.values()))
    return dict(paths=result, path_count=4, unconstrained_endpoint_count=0,
                all_receiver_queries_in_domain=all(r["receiver_constraint"]["inside_table_domain"] for r in result.values()),
                max_abs_error_ns=max(r["max_abs_error_ns"] for r in result.values()),
                receiver_library_sha256=hashlib.sha256(Path(receiver_library).read_bytes()).hexdigest(),
                propagation_reference="STA increments; not independently simulated",
                constraint_reference="direct loaded-Liberty interpolation at reported pin slews",
                physical_validation=False)
