"""Real-library opposite-edge lane harness; not a qualified pad/PHY model."""

import hashlib
import json
from pathlib import Path
import re
import subprocess

from .interconnect import estimate_links


NETLIST = '''module lane(input clk, input din, output dout);
wire tx_q, data, fwd, capture_clk;
sky130_fd_sc_hd__dfxtp_1 tx_reg (.CLK(clk), .D(din), .Q(tx_q));
sky130_fd_sc_hd__buf_8 tx_data (.A(tx_q), .X(data));
sky130_fd_sc_hd__buf_8 tx_clock (.A(clk), .X(fwd));
gf180mcu_fd_sc_mcu7t5v0__inv_1 rx_clock (.I(fwd), .ZN(capture_clk));
gf180mcu_fd_sc_mcu7t5v0__dffq_1 rx_reg (.CLK(capture_clk), .D(data), .Q(dout));
endmodule
'''


def parse_sta_log(log, links):
    import math
    if re.search(r"(^|\n)(Error:|Error |Warning:|.*invalid command name)", log):
        raise ValueError("OpenSTA reported errors or warnings")
    if "max_capacitance" in log or "max_slew" in log:
        raise ValueError("electrical design-rule violation; lane result is outside declared limits")
    matches = dict(re.findall(r"LANE_SLACK_(max|min)\s+([-+0-9.eE]+)", log))
    if matches.keys() != {"max", "min"} or not all(math.isfinite(float(v)) for v in matches.values()):
        raise ValueError("missing/invalid setup or hold timing result")
    wire_caps = re.findall(r"Wire capacitance:\s+([0-9.eE+-]+)", log)
    expected_caps = [next(link["assumed_c_pf"] for link in links if link["kind"] == kind) for kind in ("data", "clock")]
    if len(wire_caps) != 2 or any(not math.isclose(float(a), b, rel_tol=1e-5, abs_tol=1e-8) for a, b in zip(wire_caps, expected_caps)):
        raise ValueError("data/clock parasitic capacitance annotation mismatch")
    return matches, wire_caps


def spef_network(name, source, target, resistance_ohm, capacitance_pf, segments=8):
    import math
    if not math.isfinite(resistance_ohm) or not math.isfinite(capacitance_pf):
        raise ValueError("nonfinite channel R/C")
    if resistance_ohm <= 0 or capacitance_pf <= 0 or type(segments) is not int or segments < 1:
        raise ValueError("SPEF channel requires positive R/C and integer segments >= 1")
    nodes = [source] + [f"{name}:{i}" for i in range(1, segments)] + [target]
    lines = [f"*D_NET {name} {capacitance_pf:.12g}", "*CONN", f"*I {source} O", f"*I {target} I", "*CAP"]
    for i, node in enumerate(nodes):
        cap = capacitance_pf / segments * (0.5 if i in (0, segments) else 1)
        lines.append(f"{i+1} {node} {cap:.12g}")
    lines.append("*RES")
    for i in range(segments):
        lines.append(f"{i+1} {nodes[i]} {nodes[i+1]} {resistance_ohm / segments:.12g}")
    return "\n".join(lines + ["*END", ""])


def run_timing(case, output, sta, sky_lib, gf_lib, period_ns=20.0, data_r_scale=1.0, clock_r_scale=1.0):
    import math
    if any(not math.isfinite(v) or v <= 0 for v in (period_ns, data_r_scale, clock_r_scale)):
        raise ValueError("period and R scales must be positive finite values")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f"timing output already exists: {output}")
    sta, sky_lib, gf_lib = [Path(p).resolve(strict=True) for p in (sta, sky_lib, gf_lib)]
    for path in (sta, sky_lib, gf_lib, output):
        if any(c in str(path) for c in "{}\n\r"):
            raise ValueError("unsupported character in tool/model path")
    # This harness intentionally fixes the endpoint semantics; arbitrary topologies need their own netlist.
    links = estimate_links(case)
    if sorted(link["kind"] for link in links) != ["clock", "data"]:
        raise ValueError("lane harness requires exactly one data and one clock link")
    if any(link["source"]["chiplet"] != "tx" or link["target"]["chiplet"] != "rx" for link in case.links):
        raise ValueError("lane harness requires links from tx to rx")
    if any(link[end]["port"] != link["kind"] for link in case.links for end in ("source", "target")):
        raise ValueError("lane harness requires ports named data and clock")
    libraries = []
    for path, cell in ((sky_lib, "sky130_fd_sc_hd__dfxtp_1"), (gf_lib, "gf180mcu_fd_sc_mcu7t5v0__dffq_1")):
        content = path.read_text()
        voltage = re.search(r"nom_voltage\s*:\s*([-+0-9.eE]+)\s*;", content)
        temperature = re.search(r"nom_temperature\s*:\s*([-+0-9.eE]+)\s*;", content)
        if cell not in content or not voltage or not temperature or float(voltage[1]) != 1.8 or float(temperature[1]) != 25:
            raise ValueError(f"expected TT 25 C 1.8 V lane library: {path.name}")
        if not re.search(r'time_unit\s*:\s*"?1ns"?\s*;', content):
            raise ValueError("lane harness requires ns Liberty units")
        metadata = {}
        for key in ("nom_voltage", "nom_temperature", "input_threshold_pct_rise", "output_threshold_pct_rise",
                    "slew_lower_threshold_pct_rise", "slew_upper_threshold_pct_rise", "slew_derate_from_library"):
            found = re.search(rf"{key}\s*:\s*([-+0-9.eE]+)\s*;", content)
            metadata[key] = float(found[1]) if found else (1.0 if key == "slew_derate_from_library" else None)
        libraries.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "metadata": metadata})
    output.mkdir(parents=True)
    (output / "lane.v").write_text(NETLIST)
    (output / "wire_models.lib").write_text('''library(wire_models) {
time_unit : "1ns"; voltage_unit : "1V"; current_unit : "1mA";
capacitive_load_unit(1,pf); pulling_resistance_unit : "1kohm";
input_threshold_pct_rise : 50; input_threshold_pct_fall : 50;
output_threshold_pct_rise : 50; output_threshold_pct_fall : 50;
slew_lower_threshold_pct_rise : 20; slew_lower_threshold_pct_fall : 20;
slew_upper_threshold_pct_rise : 80; slew_upper_threshold_pct_fall : 80;
wire_load(Zero) { resistance : 0; capacitance : 0; slope : 0; fanout_length(1,0); }
}''')
    spef = '*SPEF "IEEE 1481-1998"\n*DESIGN "lane"\n*DATE "pinned-generated"\n*VENDOR "chiplet_floorplanning"\n*PROGRAM "lane"\n*VERSION "1"\n*DESIGN_FLOW "NAME_SCOPE LOCAL"\n*DIVIDER /\n*DELIMITER :\n*BUS_DELIMITER [ ]\n*T_UNIT 1 NS\n*C_UNIT 1 PF\n*R_UNIT 1 OHM\n*L_UNIT 1 HENRY\n'
    for link in links:
        if link["kind"] == "data":
            name, source, target, scale = "data", "tx_data:X", "rx_reg:D", data_r_scale
        else:
            name, source, target, scale = "fwd", "tx_clock:X", "rx_clock:I", clock_r_scale
        spef += spef_network(name, source, target, link["assumed_r_ohm"] * scale, link["assumed_c_pf"])
    (output / "package.spef").write_text(spef)
    script = f'''read_liberty {{{sky_lib}}}
read_liberty {{{gf_lib}}}
read_liberty wire_models.lib
set link_make_black_boxes 0
read_verilog lane.v
link_design lane
set_wire_load_model -name Zero -library wire_models
create_clock -name launch -period {period_ns:.12g} [get_ports clk]
create_generated_clock -name capture -source [get_ports clk] -divide_by 1 -invert [get_pins rx_clock/ZN]
set_propagated_clock [all_clocks]
set_clock_transition 0.1 [get_clocks launch]
set_input_transition 0.1 [get_ports {{din clk}}]
set_input_delay -clock launch -max 0.2 [get_ports din]
set_input_delay -clock launch -min 0.1 [get_ports din]
set_output_delay -clock capture -max 0.2 [get_ports dout]
set_output_delay -clock capture -min 0.1 [get_ports dout]
read_spef package.spef
check_setup -verbose
report_net -connections -verbose -digits 9 data
report_net -connections -verbose -digits 9 fwd
report_check_types -max_slew -max_capacitance -violators
report_checks -from [get_cells tx_reg] -to [get_cells rx_reg] -path_delay min_max -format full_clock_expanded -fields {{slew cap input_pin nets fanout}} -digits 9
foreach mode {{max min}} {{
    set paths [find_timing_paths -from [get_cells tx_reg] -to [get_cells rx_reg] -path_delay $mode]
    if {{[llength $paths] == 0}} {{ error "missing lane path $mode" }}
    foreach path $paths {{ puts "LANE_SLACK_$mode [get_property $path slack]" }}
}}
exit
'''
    (output / "run.tcl").write_text(script)
    run = subprocess.run([str(sta), "-exit", "run.tcl"], cwd=output, capture_output=True, text=True, timeout=120)
    log = run.stdout + run.stderr
    (output / "sta.log").write_text(log)
    if run.returncode:
        raise ValueError(f"OpenSTA failed; inspect {output / 'sta.log'}")
    matches, wire_caps = parse_sta_log(log, links)
    report = {"status": "analyzed_core_cell_harness", "boundary": "no_pads_no_ESD_no_PHY_qualification",
              "operating_temperature_c": 25.0, "operating_voltage_v": 1.8,
              "thermal_timing_coupling": "not_implemented", "corner_coverage": "TT_only_not_signoff",
              "internal_wires": "explicit_zero_wire_load_model",
              "electrical_design_rule_checks": "no_reported_max_capacitance_or_max_slew_violation",
              "libraries": libraries, "period_ns": period_ns,
              "annotated_wire_cap_pf": dict(zip(("data", "clock"), map(float, wire_caps))),
              "setup_slack_ns": float(matches["max"]), "hold_slack_ns": float(matches["min"]),
              "package_r_scale": {"data": data_r_scale, "clock": clock_r_scale},
              "links": links, "tool_version": subprocess.check_output([str(sta), "-version"], text=True).strip(),
              "sta_sha256": hashlib.sha256(sta.read_bytes()).hexdigest(),
              "input_sha256": hashlib.sha256(json.dumps(case.input_data, sort_keys=True).encode()).hexdigest()}
    (output / "timing.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
