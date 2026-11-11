"""Synthetic constant Liberty fixture, separate from the event-time oracle."""

NETLIST = """module lane(input clk, input d, output q);
wire tx_q, data, forwarded, captured;
FF tx_reg (.CK(clk), .D(d), .Q(tx_q));
DATA tx_data (.A(tx_q), .Y(data));
CLOCK tx_clock (.A(clk), .Y(forwarded));
INV rx_clock (.A(forwarded), .Y(captured));
FF rx_reg (.CK(captured), .D(data), .Q(q));
endmodule
"""


def scalar(name, value):
    return f'{name} (scalar) {{ values ("{value:.9f}"); }}'


def propagation(rise, fall):
    return "\n".join((scalar("cell_rise", rise), scalar("cell_fall", fall),
                      scalar("rise_transition", 0.1), scalar("fall_transition", 0.1)))


def library(c):
    text = '''library (semantic_fixture) {
delay_model : table_lookup;
time_unit : "1ns";
voltage_unit : "1V";
current_unit : "1mA";
pulling_resistance_unit : "1kohm";
capacitive_load_unit (1, pf);
nom_process : 1; nom_voltage : 1; nom_temperature : 25;
input_threshold_pct_rise : 50; input_threshold_pct_fall : 50;
output_threshold_pct_rise : 50; output_threshold_pct_fall : 50;
slew_lower_threshold_pct_rise : 20; slew_lower_threshold_pct_fall : 20;
slew_upper_threshold_pct_rise : 80; slew_upper_threshold_pct_fall : 80;
default_max_transition : 1.0;
'''
    for name, delays, invert in (("DATA", c.data_ns, False),
                                 ("CLOCK", c.clock_ns, False),
                                 ("INV", c.inverter_ns, True)):
        text += f'''cell ({name}) {{ area : 1;
pin (A) {{ direction : input; capacitance : 0.01; }}
pin (Y) {{ direction : output; function : "{'!A' if invert else 'A'}";
max_capacitance : 1;
timing () {{ related_pin : "A"; timing_type : combinational;
timing_sense : {'negative_unate' if invert else 'positive_unate'};
{propagation(*delays)} }} }} }}
'''
    text += '''cell (FF) { area : 1;
ff (IQ, IQN) { clocked_on : "CK"; next_state : "D"; }
pin (CK) { direction : input; clock : true; capacitance : 0.01; }
pin (D) { direction : input; capacitance : 0.01;
'''
    for check, values in (("setup", c.setup_ns), ("hold", c.hold_ns)):
        text += f'''timing () {{ related_pin : "CK"; timing_type : {check}_rising;
{scalar('rise_constraint', values[0])}
{scalar('fall_constraint', values[1])} }}
'''
    text += f'''}}
pin (Q) {{ direction : output; function : "IQ"; max_capacitance : 1;
timing () {{ related_pin : "CK"; timing_type : rising_edge;
timing_sense : non_unate; {propagation(*c.cq_ns)} }} }} }} }}
'''
    return text


def script(c, mutation=None, min_max=False):
    tcl = ("read_liberty -min early.lib\nread_liberty -max fixture.lib\n"
           if min_max else "read_liberty fixture.lib\n")
    tcl += f'''read_verilog lane.v
link_design lane
create_clock -name launch -period {c.period_ns} -waveform {{0 {c.fall_ns}}} [get_ports clk]
'''
    if mutation != "missing_generated_clock":
        invert = "" if mutation == "missing_invert" else "-invert"
        tcl += f'''create_generated_clock -name capture -source [get_ports clk] -divide_by 1 {invert} [get_pins rx_clock/Y]
'''
    tcl += '''set_propagated_clock [all_clocks]
set_clock_transition 0.1 [all_clocks]
set_input_delay -clock launch 0.0 [get_ports d]
set_output_delay -clock launch 0.0 [get_ports q]
set_input_transition 0.1 [get_ports d]
set_load 0.01 [get_ports q]
'''
    if mutation == "ideal_capture":
        tcl += "unset_propagated_clock [get_clocks capture]\n"
    if mutation == "missing_constraints":
        tcl = tcl.replace("set_output_delay -clock launch 0.0 [get_ports q]\n", "")
    if min_max:
        tcl += "set_operating_conditions -analysis_type on_chip_variation\n"
    tcl += '''puts "ORACLE_CHECKS_BEGIN"
check_setup -verbose
report_check_types -max_slew -max_capacitance -violators
puts "ORACLE_CHECKS_END"
report_clock_properties [all_clocks]
'''
    for check, delay in (("setup", "max"), ("hold", "min")):
        for transition in ("rise", "fall"):
            tcl += f'''puts "ORACLE_BEGIN {check}_{transition}"
report_checks -from [get_cells tx_reg] -{transition}_to [get_pins rx_reg/D] -path_delay {delay} -format full_clock_expanded -fields {{slew cap}} -digits 6
puts "ORACLE_END {check}_{transition}"
'''
    return tcl
