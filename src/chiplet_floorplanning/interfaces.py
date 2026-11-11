"""Explicit, fixed-mode low-speed source-synchronous GPIO prototypes.

Supplies describe the selected Liberty operating points. Power pins are implicit
in the logical netlist; this is not a pad-ring, power-sequencing or ESD design.
"""

CORE_NETLIST = '''module lane(input clk, input din, output dout);
wire tx_q, data, fwd, capture_clk;
sky130_fd_sc_hd__dfxtp_1 tx_reg (.CLK(clk), .D(din), .Q(tx_q));
sky130_fd_sc_hd__buf_8 tx_data (.A(tx_q), .X(data));
sky130_fd_sc_hd__buf_8 tx_clock (.A(clk), .X(fwd));
gf180mcu_fd_sc_mcu7t5v0__inv_1 rx_clock (.I(fwd), .ZN(capture_clk));
gf180mcu_fd_sc_mcu7t5v0__dffq_1 rx_reg (.CLK(capture_clk), .D(data), .Q(dout));
endmodule
'''


def forward_pad_netlist():
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


SKY_RX_CONTROLS = {
    'OE_N': 1, 'INP_DIS': 0, 'SLOW': 0, 'HLD_H_N': 1, 'HLD_OVR': 0,
    'ENABLE_H': 1, 'ENABLE_VDDA_H': 0, 'ENABLE_INP_H': 0,
    'ENABLE_VDDIO': 1, 'ENABLE_VSWITCH_H': 1, 'VTRIP_SEL': 0,
    'IB_MODE_SEL': 0, 'ANALOG_EN': 0, 'ANALOG_SEL': 0, 'ANALOG_POL': 0, 'OUT': 0,
}
GF_TX_CONTROLS = {'OE': 1, 'IE': 0, 'PDRV0': 1, 'PDRV1': 1,
                  'CS': 0, 'SL': 0, 'PU': 0, 'PD': 0}


def reverse_pad_netlist():
    """GF 3.3 V TX -> SKY 3.3 V input / 1.8 V core; rising launch, falling capture.

    Actual receiver buffers keep the pad output loads within its characterized
    table domain (>= 0.01 pF); no invented capacitance or modified PDK limit.
    """
    lines = ['module lane(input clk, input din, output dout);',
             'wire tx_q, tx_d, tx_c, data, fwd, rx_d, rx_c, rx_buffered, capture_clk;',
             'gf180mcu_fd_sc_mcu7t5v0__dffq_1 tx_reg (.CLK(clk), .D(din), .Q(tx_q));',
             'gf180mcu_fd_sc_mcu7t5v0__buf_8 tx_data (.I(tx_q), .Z(tx_d));',
             'gf180mcu_fd_sc_mcu7t5v0__buf_8 tx_clock (.I(clk), .Z(tx_c));']
    sky_pins = [f".{p}(1'b{v})" for p, v in SKY_RX_CONTROLS.items()]+[".DM(3'b001)"]
    gf_pins = [f".{p}(1'b{v})" for p, v in GF_TX_CONTROLS.items()]
    for name, source, net, target in [('data', 'tx_d', 'data', 'rx_d'), ('clock', 'tx_c', 'fwd', 'rx_c')]:
        lines.append(f'gf180mcu_fd_io__bi_t tx_{name}_pad (.A({source}), .PAD({net}), '+', '.join(gf_pins)+');')
        lines.append(f'sky130_ef_io__gpiov2_pad rx_{name}_pad (.PAD({net}), .IN({target}), '+', '.join(sky_pins)+');')
    lines += ['sky130_fd_sc_hd__buf_16 rx_data (.A(rx_d), .X(rx_buffered));',
              'sky130_fd_sc_hd__inv_8 rx_clock (.A(rx_c), .Y(capture_clk));',
              'sky130_fd_sc_hd__dfxtp_1 rx_reg (.CLK(capture_clk), .D(rx_buffered), .Q(dout));', 'endmodule']
    return '\n'.join(lines)+'\n'


def reverse_contract():
    return {'direction': 'gf180_to_sky130', 'protocol': 'single_data_lane_source_synchronous_SDR',
            'launch_edge': 'rising', 'capture_edge': 'forwarded_falling_via_receiver_inverter',
            'clock_duty_cycle': 0.5, 'tx_core_voltage_v': 3.3, 'rx_core_voltage_v': 1.8,
            'tx_io_voltage_v': 3.3, 'rx_io_voltage_v': 3.3, 'temperature_c': 25.0,
            'tx_cell': 'gf180mcu_fd_io__bi_t', 'rx_cell': 'sky130_ef_io__gpiov2_pad',
            'tx_controls': dict(GF_TX_CONTROLS), 'rx_controls': {**SKY_RX_CONTROLS, 'DM': '001'},
            'pad_capacitance_owner': 'Liberty_only_not_duplicated_in_package_SPEF',
            'bump_parasitics': 'not_included', 'internal_wire_parasitics': 'zero_assumption',
            'clock_uncertainty_ns': 0.0, 'clock_uncertainty_status': 'ideal_clock_assumption_not_measured_jitter',
            'sources': ['https://gf180mcu-pdk.readthedocs.io/en/latest/IPs/IO/gf180mcu_fd_io/digital.html',
                        'https://skywater-pdk.readthedocs.io/en/main/contents/libraries/sky130_fd_io/docs/user_guide.html'],
            'qualification': 'library_timing_prototype_not_physical_link_validation'}
