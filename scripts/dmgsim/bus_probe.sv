// A probe for msinger's dmg-sim (SystemVerilog netlist of the DMG-CPU B): a second top-level
// module that prints the SM83 core's own bus signals whenever any of them changes, so
// scripts/dmgsim_run.py can recover the CPU's bus M-cycle by M-cycle without dumping the whole
// design (docs/validation.md rung 5).
//
// It reads the nets of the `dmg` instance inside dmg_cpu_b_gameboy: `cpu_port_a` and
// `cpu_port_d` are the core's address and data ports (not the external pins, which hold a stale
// address with A15 forced high on cycles that make no cartridge access), `read`, `write` and
// `mreq` its strobes, `m1` the opcode-fetch flag and `clk_ena` the halt state (low while halted) and `iflag` the five interrupt-flag bits.
// `phi` is the 1 MHz cartridge clock: one period per M-cycle.
//
// One line per change: "<time ns> <phi> <a hex> <rd> <wr> <mreq> <m1> <clk_ena> <d hex> <IF hex>".
//
// SPDX-License-Identifier: MIT

`default_nettype none

module bus_probe;
	wire        phi     = dmg_cpu_b_gameboy.phi;
	wire [15:0] a       = dmg_cpu_b_gameboy.dmg.cpu_port_a;
	wire [7:0]  d       = dmg_cpu_b_gameboy.dmg.cpu_port_d;
	wire        rd      = dmg_cpu_b_gameboy.dmg.read;
	wire        wr      = dmg_cpu_b_gameboy.dmg.write;
	wire        mreq    = dmg_cpu_b_gameboy.dmg.mreq;
	wire        m1      = dmg_cpu_b_gameboy.dmg.m1;
	wire        clk_ena = dmg_cpu_b_gameboy.dmg.clk_ena;
	wire [4:0]  iflag   = dmg_cpu_b_gameboy.reg_ff0f[4:0];

	initial $monitor("%0d %b %h %b %b %b %b %b %h %h",
		$time, phi, a, rd, wr, mreq, m1, clk_ena, d, iflag);
endmodule
