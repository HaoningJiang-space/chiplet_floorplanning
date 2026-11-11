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


def pad_netlist():
    """Static digital push-pull GPIO mode, with input/pull/analog paths disabled."""
    lines = ['module lane(input clk, input din, output dout);',
             'wire tx_q, tx_d, tx_c, data, fwd, rx_d, rx_c, capture_clk;',
             'sky130_fd_sc_hd__dfxtp_1 tx_reg (.CLK(clk), .D(din), .Q(tx_q));',
             'sky130_fd_sc_hd__buf_8 tx_data (.A(tx_q), .X(tx_d));',
             'sky130_fd_sc_hd__buf_8 tx_clock (.A(clk), .X(tx_c));']
    controls = {'OE_N': 0, 'INP_DIS': 1, 'SLOW': 0, 'HLD_H_N': 1,
                'HLD_OVR': 0, 'ENABLE_H': 1, 'ENABLE_VDDA_H': 0,
                'ENABLE_INP_H': 0, 'ENABLE_VDDIO': 1, 'ENABLE_VSWITCH_H': 1,
                'VTRIP_SEL': 0, 'IB_MODE_SEL': 0, 'ANALOG_EN': 0,
                'ANALOG_SEL': 0, 'ANALOG_POL': 0}
    pins = [f'.{pin}(1\'b{value})' for pin, value in controls.items()]
    pins += [".DM(3'b110)"]
    for name, source, net, target in [('data', 'tx_d', 'data', 'rx_d'), ('clock', 'tx_c', 'fwd', 'rx_c')]:
        lines.append(f'sky130_ef_io__gpiov2_pad tx_{name}_pad (.OUT({source}), .PAD({net}), '+', '.join(pins)+');')
        lines.append(f'gf180mcu_fd_io__in_c rx_{name}_pad (.PAD({net}), .Y({target}), .PU(1\'b0), .PD(1\'b0));')
    lines += ['gf180mcu_fd_sc_mcu7t5v0__inv_1 rx_clock (.I(rx_c), .ZN(capture_clk));',
              'gf180mcu_fd_sc_mcu7t5v0__dffq_1 rx_reg (.CLK(capture_clk), .D(rx_d), .Q(dout));', 'endmodule']
    return '\n'.join(lines)+'\n'


def parse_sta_log(log, links):
    import math
    if re.search(r"(^|\n)(Error:|Error |Warning:|.*invalid command name)", log):
        raise ValueError("OpenSTA reported errors or warnings")
    electrical = log.split('Startpoint:', 1)[0]
    if re.search(r'max[_ ](?:capacitance|slew)', electrical) and '(VIOLATED)' in electrical:
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


def run_timing(case, output, sta, sky_lib, gf_lib, period_ns=20.0, data_r_scale=1.0, clock_r_scale=1.0,
               sky_pad_lib=None, gf_pad_lib=None, characterized_corners=False, instance_models=None):
    import math
    if any(not math.isfinite(v) or v <= 0 for v in (period_ns, data_r_scale, clock_r_scale)):
        raise ValueError("period and R scales must be positive finite values")
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f"timing output already exists: {output}")
    sta, sky_lib, gf_lib = [Path(p).resolve(strict=True) for p in (sta, sky_lib, gf_lib)]
    if bool(sky_pad_lib) != bool(gf_pad_lib):
        raise ValueError('both pad libraries are required')
    pads = bool(sky_pad_lib)
    paths = [sky_lib, gf_lib]
    if pads:
        paths += [Path(p).resolve(strict=True) for p in (sky_pad_lib, gf_pad_lib)]
    instance_models = instance_models or {}
    if pads and instance_models:
        raise ValueError('local pad temperature characterization is not available')
    allowed_instances = {'tx_reg', 'tx_data', 'tx_clock', 'rx_clock', 'rx_reg'}
    if instance_models.keys() - allowed_instances:
        raise ValueError('unknown lane instance in temperature assignment')
    for model in instance_models.values():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', model['cell']):
            raise ValueError('invalid instance library cell name')
        paths.append(Path(model['path']).resolve(strict=True))
    for path in [sta, output] + paths:
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
    expected_cells = ['sky130_fd_sc_hd__dfxtp_1', 'gf180mcu_fd_sc_mcu7t5v0__dffq_1']
    if pads:
        expected_cells += ['sky130_ef_io__gpiov2_pad', 'gf180mcu_fd_io__in_c']
    expected_cells += [model['cell'] for model in instance_models.values()]
    for index, (path, cell) in enumerate(zip(paths, expected_cells)):
        content = path.read_text()
        voltage = re.search(r"nom_voltage\s*:\s*([-+0-9.eE]+)\s*;", content)
        temperature = re.search(r"nom_temperature\s*:\s*([-+0-9.eE]+)\s*;", content)
        if not re.search(r'cell\s*\(\s*"?'+re.escape(cell)+r'"?\s*\)', content) or not voltage or not temperature:
            raise ValueError(f"missing expected cell or PVT metadata: {path.name}")
        expected_v = (1.8, 3.3, 1.8, 3.3)[index] if pads else 1.8
        if (pads or (not characterized_corners and not instance_models)) and (float(voltage[1]) != expected_v or float(temperature[1]) != 25):
            raise ValueError(f"expected fixed TT 25 C {expected_v} V lane library: {path.name}")
        if not all(math.isfinite(float(v[1])) for v in (voltage, temperature)) or float(voltage[1]) <= 0:
            raise ValueError('invalid library operating point')
        if pads and index == 2:
            supply = re.search(r'voltage_map\s*\(\s*"?VDDIO"?\s*,\s*([-+0-9.eE]+)\s*\)', content)
            if not supply or float(supply[1]) != 3.3:
                raise ValueError('SKY130 pad requires a characterized 3.3 V VDDIO domain')
        if not re.search(r'time_unit\s*:\s*"?1ns"?\s*;', content):
            raise ValueError("lane harness requires ns Liberty units")
        metadata = {}
        for key in ("nom_voltage", "nom_temperature", "input_threshold_pct_rise", "output_threshold_pct_rise",
                    "slew_lower_threshold_pct_rise", "slew_upper_threshold_pct_rise", "slew_derate_from_library"):
            found = re.search(rf"{key}\s*:\s*([-+0-9.eE]+)\s*;", content)
            metadata[key] = float(found[1]) if found else (1.0 if key == "slew_derate_from_library" else None)
        libraries.append({"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "metadata": metadata})
    output.mkdir(parents=True)
    netlist = pad_netlist() if pads else NETLIST
    for instance, model in instance_models.items():
        netlist, count = re.subn(r'\b\w+\s+'+re.escape(instance)+r'\s+\(', model['cell']+' '+instance+' (', netlist)
        if count != 1:
            raise ValueError('instance replacement did not match exactly once')
    (output / "lane.v").write_text(netlist)
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
        if pads:
            source, target = f'tx_{link["kind"]}_pad:PAD', f'rx_{link["kind"]}_pad:PAD'
        spef += spef_network(name, source, target, link["assumed_r_ohm"] * scale, link["assumed_c_pf"])
    (output / "package.spef").write_text(spef)
    script = ''.join(f'read_liberty {{{path}}}\n' for path in dict.fromkeys(paths)) + f'''read_liberty wire_models.lib
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
puts "DCALC_TX_DATA_BEGIN"
report_dcalc -from tx_data/A -to tx_data/X -max -digits 9
puts "DCALC_TX_DATA_END"
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
    if pads or characterized_corners or instance_models:
        report.pop('operating_temperature_c')
        report.pop('operating_voltage_v')
        report['corner_coverage'] = 'explicit_library_points_only_not_full_PVT'
    if pads:
        report.update(status='analyzed_GPIO_pad_harness', boundary='Liberty_pad_timing_not_SI_BER_or_PHY_qualification',
                      io_voltage_v=3.3, pad_mode='SKY130_DM110_fast_push_pull_GF180_pulls_disabled')
    if instance_models:
        report['thermal_timing_coupling'] = 'per_instance_Liberty_assignment_interpolation_accuracy_unvalidated'
        report['instance_models'] = {name: {k: v for k, v in model.items() if k != 'path'} for name, model in instance_models.items()}
    (output / "timing.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
