// Original testbench for unchanged pinned PULP PHY modules (SDR subset).
// Ideal inertial digital delay; no pad, PDK, SI, or metastability model.
`timescale 1ns/1ps
module slink_phy_tb;
    parameter int Width = 8;
    parameter int Divider = 8;
    parameter int DataDelayNs = 2;
    parameter int ClockDelayNs = 2;
    localparam int Words = 128;
    typedef logic [Width-1:0] word_t;
    logic tx_clk = 0, rx_clk = 0;
    logic rst_n = 0;
    logic valid = 0, ready, fwd_clk, channel_clk;
    logic rx_valid, rx_ready = 0;
    word_t tx_data = 0, pins, channel_data, rx_data;
    int sent = 0, received = 0, rx_cycles = 0;
    word_t expected[$];
    always #5 tx_clk = ~tx_clk;
    always #6.5 rx_clk = ~rx_clk;
    assign #(DataDelayNs) channel_data = pins;
    assign #(ClockDelayNs) channel_clk = fwd_clk;

    slink_phys_layer_tx #(.NumLanes(Width), .EnDdr(0), .phy_data_t(word_t)) tx (
        .clk_i(tx_clk), .rst_ni(rst_n), .clk_div_i(6'(Divider)),
        .clk_shift_start_i(6'(Divider/4)), .clk_shift_end_i(6'(3*Divider/4)),
        .data_out_i(tx_data), .data_out_valid_i(valid), .data_out_ready_o(ready),
        .ddr_rcv_clk_o(fwd_clk), .ddr_o(pins)
    );
    slink_phys_layer_rx #(.NumLanes(Width), .EnDdr(0), .phy_data_t(word_t)) rx (
        .clk_i(rx_clk), .rst_ni(rst_n), .ddr_rcv_clk_i(channel_clk),
        .data_in_o(rx_data), .data_in_valid_o(rx_valid),
        .data_in_ready_i(rx_ready), .ddr_i(channel_data)
    );

    function automatic word_t pattern(int index);
        return word_t'((index * 73) ^ (index >> 2) ^ 32'hA5);
    endfunction

    // Assert the otherwise unconnected PHY FIFO source-ready indication.
    // Bounded backpressure here is not general link-level credit flow control.
    always @(posedge channel_clk) begin
        if (rst_n && !rx.i_cdc_in.src_ready_o) $fatal(1, "FIFO_OVERFLOW");
    end
    always @(negedge rx_clk) begin
        rx_cycles = rx_cycles + 1;
        rx_ready = rst_n && (rx_cycles % 9 >= 3);
    end
    always @(posedge rx_clk) begin
        word_t value;
        if (rst_n && rx_valid && rx_ready) begin
            if (expected.size() == 0) $fatal(1, "EXTRA_WORD received=%0d sent=%0d", received, sent);
            value = expected.pop_front();
            if (rx_data !== value)
                $fatal(1, "DATA_MISMATCH index=%0d expected=%0h got=%0h", received, value, rx_data);
            received = received + 1;
        end
    end
    initial begin
        // Both domains held in reset; release away from all active edges.
        #101 rst_n = 1;
        repeat (3) @(negedge tx_clk);
        for (int i = 0; i < Words; i++) begin
            tx_data = pattern(i);
            valid = 1;
            do @(posedge tx_clk); while (!ready);
            expected.push_back(tx_data);
            sent = sent + 1;
            @(negedge tx_clk);
            // Stop only at completed transfer boundaries; exercise clock gating.
            if (i % 11 == 10) begin
                valid = 0;
                repeat (5) @(negedge tx_clk);
            end
        end
        valid = 0;
        wait (received == Words);
        repeat (50) @(posedge rx_clk);
        if (expected.size() != 0 || sent != received) $fatal(1, "COUNT_MISMATCH");
        $display("PHY_PASS words=%0d width=%0d divider=%0d", received, Width, Divider);
        $finish;
    end
    initial begin
        #100000;
        $fatal(1, "TIMEOUT sent=%0d received=%0d", sent, received);
    end
endmodule
