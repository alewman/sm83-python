-- Testbench for Gekkio's VHDL SM83 (gb-research/sm83-cpu-core): run a ROM on the die model's
-- mock SoC and write one CSV row per M-cycle: what the CPU drove on the bus, internal cycles
-- included. The columns are
--
--   cycle,addr,rd,wr,m1,data
--
-- sampled 5 ns after the rising edge of `writeback`, when the address, the read and write
-- strobes and the data bus are all valid (test_rom_tb samples a fetch at the same edge).
-- rd and wr are 1 for a read or write M-cycle; a cycle with neither is an internal cycle and
-- `addr` is what the CPU drove on the address bus that cycle (docs/validation.md rung 5). m1
-- marks an opcode fetch. data is the byte on the bus ("--" if nothing drives it).
--
-- `inject_path` names an optional schedule of interrupt requests (see `injector`); the SoC is
-- test_soc_irq.vhd, Gekkio's mock SoC plus an input for them.
--
-- The memory map is test_rom_tb's (ROM with a bank register, LY = $90, SC = $7F) on top of the
-- mock SoC's boot stub, WRAM, HRAM and IF register. The run ends at an infinite JR, as there,
-- or after `max_cycles` M-cycles.
--
-- SPDX-License-Identifier: MIT OR Apache-2.0 (this file; the model it drives is Gekkio's)

library ieee;
use ieee.numeric_std.all;
use ieee.std_logic_1164.all;
use std.textio.all;

library vunit_lib;
context vunit_lib.vunit_context;

library sm83;
use sm83.sm83_test.all;

entity bus_dump_tb is
  generic(
    runner_cfg: string;
    rom_path: string := "test.gb";
    out_path: string := "bus.csv";
    max_cycles: natural := 1_000_000;
    inject_path: string := "";
    max_duration: time := 60_000 ms
  );
end entity;

architecture tb of bus_dump_tb is
  signal rom_data: integer_array_t;
  signal rom_bank: std_ulogic_vector(7 downto 0) := X"01";

  signal clk: std_ulogic := '1';
  signal reset: std_ulogic := '1';

  signal clocks: clocks_type;
  signal bus_ctrl: soc_bus_ctrl_type;
  signal data: std_logic_vector(7 downto 0);
  signal boot_en: std_ulogic;
  signal m1: std_ulogic;
  signal irq_inject: std_ulogic_vector(4 downto 0) := (others => '0');
  signal logged: natural := 0;

  function bit_char(b: std_ulogic) return character is
  begin
    if to_x01(b) = '1' then
      return '1';
    end if;
    return '0';
  end function;

  function data_text(d: std_logic_vector(7 downto 0)) return string is
    variable u: std_ulogic_vector(7 downto 0) := to_ux01(std_ulogic_vector(d));
  begin
    for i in u'range loop
      if u(i) /= '0' and u(i) /= '1' then
        return "--";
      end if;
    end loop;
    return to_hex_string(u);
  end function;
begin
  main: process
    file out_file: text;
    variable row: line;
    variable cycle: natural := 0;
    variable last_fetch: std_ulogic_vector(15 downto 0) := (others => '0');
    variable fetched: boolean := false;
    variable fetch_data: std_ulogic_vector(7 downto 0);
    variable is_fetch: boolean;
  begin
    test_runner_setup(runner, runner_cfg);
    file_open(out_file, out_path, write_mode);
    write(row, string'("cycle,addr,rd,wr,m1,data"));
    writeline(out_file, row);

    rom_data <= load_raw(rom_path, 8, false);

    wait until rising_edge(clocks.mclk_pulse);
    reset <= '0' after 10 ns;
    wait until rising_edge(clocks.mclk_pulse);

    while cycle < max_cycles loop
      wait until rising_edge(clocks.writeback);
      wait for 5 ns;
      is_fetch := to_x01(m1) = '1';
      write(row, cycle);
      write(row, ',' & to_hex_string(to_ux01(bus_ctrl.addr)));
      write(row, ',' & bit_char(bus_ctrl.rd) & ',' & bit_char(bus_ctrl.wr));
      write(row, ',' & bit_char(m1) & ',' & data_text(data));
      writeline(out_file, row);
      cycle := cycle + 1;
      logged <= cycle;
      if is_fetch and to_x01(bus_ctrl.rd) = '1' then
        fetch_data := to_ux01(std_ulogic_vector(data));
        if fetched and last_fetch = to_ux01(bus_ctrl.addr) and fetch_data = X"18" then
          info("Terminating: infinite JR loop");
          exit;
        end if;
        last_fetch := to_ux01(bus_ctrl.addr);
        fetched := true;
      end if;
    end loop;

    file_close(out_file);
    info("Logged " & to_string(cycle) & " M-cycles");
    test_runner_cleanup(runner);
  end process;
  test_runner_watchdog(runner, max_duration);

  clk <= not clk after 119.2 ns;

  soc_inst: entity work.test_soc_irq
  port map (
    clk => clk,
    reset => reset,
    clocks => clocks,
    bus_ctrl => bus_ctrl,
    data => data,
    boot_en => boot_en,
    m1 => m1,
    irq_inject => irq_inject
  );

  -- A peripheral raising interrupts: each line of the inject file is "cycle mask"; the IF bits
  -- in `mask` are set for one M-cycle starting right after the CSV row `cycle` is written.
  injector: process
    file schedule: text;
    variable l: line;
    variable at_cycle, mask: integer;
    type int_array is array (0 to 63) of integer;
    variable cycles, masks: int_array;
    variable count: natural := 0;
  begin
    if inject_path /= "" then
      file_open(schedule, inject_path, read_mode);
      while not endfile(schedule) loop
        readline(schedule, l);
        read(l, at_cycle);
        read(l, mask);
        cycles(count) := at_cycle;
        masks(count) := mask;
        count := count + 1;
      end loop;
      file_close(schedule);
    end if;
    loop
      wait on logged;
      irq_inject <= (others => '0');
      for i in 0 to count - 1 loop
        if cycles(i) = logged - 1 then
          irq_inject <= std_ulogic_vector(to_unsigned(masks(i), 5));
        end if;
      end loop;
    end loop;
  end process;

  ppu: process(all)
  begin
    data <= X"ZZ";
    if bus_ctrl.rd then
      if bus_ctrl.addr ?= X"FF44" then
        data <= X"90";
      end if;
    end if;
  end process;

  external_rom: process(all)
  begin
    data <= X"ZZ";
    if bus_ctrl.rd and not boot_en then
      if bus_ctrl.addr < X"4000" then
        data <= read_array(rom_data, bus_ctrl.addr);
      elsif bus_ctrl.addr < X"8000" then
        data <= read_array(rom_data, rom_bank & bus_ctrl.addr(13 downto 0));
      end if;
    end if;

    if rising_edge(bus_ctrl.wr) then
      if bus_ctrl.addr >= X"2000" and bus_ctrl.addr < X"2FFF" then
        rom_bank <= data;
      end if;
    end if;
  end process;

  serial: process(all)
  begin
    data <= X"ZZ";
    if bus_ctrl.rd then
      if bus_ctrl.addr ?= X"FF02" then
        data <= X"7F";
      end if;
    end if;
  end process;
end architecture;
