"""One common clock root/trunk with explicit buffered launch/capture fanout."""

from .timing_fixture import library, propagation
from .timing_oracle import Contract


def bounds(c, name, early):
    values = getattr(c, name+'_ns')
    if not early:
        return values
    return tuple(x-.2 for x in values) if name == 'root' else tuple(.7*x for x in values)


def cell(name, delays, maximum_cap=1.):
    return f'''cell ({name}) {{ area : 1;
pin (A) {{ direction : input; capacitance : 0.01; }}
pin (Y) {{ direction : output; function : "A"; max_capacitance : {maximum_cap};
timing () {{ related_pin : "A"; timing_type : combinational; timing_sense : positive_unate;
{propagation(*delays)} }} }} }}
'''


def libraries(c, early=False, mutation=None):
    text = library(Contract(cq_ns=bounds(c, 'cq', early), inverter_ns=bounds(c, 'inverter', early),
                            setup_ns=c.setup_ns, hold_ns=c.hold_ns))
    text = text[:text.rfind('}')]
    text += cell('ROOT', bounds(c, 'root', early))
    text += cell('TRUNK', bounds(c, 'trunk', early))
    text += cell('BANK', bounds(c, 'bank', early), .04 if mutation == 'overloaded_bank' else 1.)
    scale = .7 if early else 1.
    for receiver in range(c.receivers):
        text += cell(f'BRANCH_{receiver}', tuple(scale*v for v in c.branch(receiver)))
        for lane in range(c.lanes):
            text += cell(f'DATA_{receiver}_{lane}', tuple(scale*v for v in c.data(receiver, lane)))
    return (text+'}\n').replace('semantic_fixture', 'multilane_early' if early else 'multilane_late')


def netlist(c):
    total = c.receivers*c.lanes
    lines = [f'module fabric(input clk, input [{total-1}:0] d, output [{total-1}:0] q);',
             'wire common, forwarded;', 'ROOT clock_root (.A(clk), .Y(common));',
             'TRUNK clock_trunk (.A(common), .Y(forwarded));']
    for receiver in range(c.receivers):
        lines += [f'wire launch_{receiver}, branch_{receiver}, capture_{receiver};',
            f'BANK bank_{receiver} (.A(common), .Y(launch_{receiver}));',
            f'BRANCH_{receiver} branch_{receiver}_cell (.A(forwarded), .Y(branch_{receiver}));',
            f'INV inv_{receiver} (.A(branch_{receiver}), .Y(capture_{receiver}));']
        for lane in range(c.lanes):
            suffix = f'{receiver}_{lane}'; port = receiver*c.lanes+lane
            lines += [f'wire txq_{suffix}, data_{suffix};',
                f'FF tx_{suffix} (.CK(launch_{receiver}), .D(d[{port}]), .Q(txq_{suffix}));',
                f'DATA_{suffix} data_cell_{suffix} (.A(txq_{suffix}), .Y(data_{suffix}));',
                f'FF rx_{suffix} (.CK(capture_{receiver}), .D(data_{suffix}), .Q(q[{port}]));']
    return '\n'.join(lines+['endmodule', ''])


def script(c, min_max=False, correlated=False, mutation=None):
    lines = ['read_liberty -min early.lib', 'read_liberty -max fixture.lib'] if min_max else ['read_liberty fixture.lib']
    lines += ['read_verilog fabric.v', 'link_design fabric',
        f'create_clock -name launch -period {c.period_ns} -waveform {{0 {c.fall_ns}}} [get_ports clk]']
    for receiver in range(c.receivers):
        if mutation == 'missing_capture_clock' and receiver == c.receivers-1:
            continue
        invert = '' if mutation == 'wrong_capture_polarity' and receiver == 0 else '-invert'
        lines += [f'create_generated_clock -name capture_{receiver} -source [get_ports clk] -divide_by 1 {invert} [get_pins inv_{receiver}/Y]']
    lines += ['set_propagated_clock [all_clocks]', 'set_clock_transition 0.1 [all_clocks]',
        'set_input_delay -clock launch 0.0 [get_ports d*]', 'set_output_delay -clock launch 0.0 [get_ports q*]',
        'set_input_transition 0.1 [get_ports d*]', 'set_load 0.01 [get_ports q*]',
        f'set sta_crpr_enabled {1 if correlated else 0}', 'set sta_crpr_mode same_pin']
    if min_max:
        lines += ['set_operating_conditions -analysis_type on_chip_variation']
    lines += ['puts "NETWORK_CHECKS_BEGIN"', 'check_setup -verbose',
        'report_check_types -max_slew -max_capacitance -violators', 'puts "NETWORK_CHECKS_END"',
        'report_clock_properties [all_clocks]']
    for receiver in range(c.receivers):
        for lane in range(c.lanes):
            suffix = f'{receiver}_{lane}'
            for check, delay in (('setup', 'max'), ('hold', 'min')):
                for transition in ('rise', 'fall'):
                    key = f'{suffix}_{check}_{transition}'
                    if mutation == 'missing_last_lane' and (receiver, lane) == (c.receivers-1, c.lanes-1):
                        continue
                    endpoint = f'rx_{suffix}/D'
                    if mutation == 'wrong_lane_endpoint' and (receiver, lane) == (0, 0):
                        endpoint = 'rx_0_1/D'
                    lines += [f'puts "NETWORK_BEGIN {key}"',
                        f'report_checks -from [get_cells tx_{suffix}] -{transition}_to [get_pins {endpoint}] -path_delay {delay} -format full_clock_expanded -fields {{slew cap}} -digits 6',
                        f'puts "NETWORK_END {key}"']
    return '\n'.join(lines)+'\n'
