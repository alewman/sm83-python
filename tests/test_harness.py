"""The minimal harness itself: memory map, serial port, DIV, stop conditions."""

from sm83_python.harness import SERIAL_CYCLES, Harness, post_boot_state


def rom(program: bytes, at: int = 0x0100, size: int = 0x8000) -> bytes:
    data = bytearray(size)
    data[at : at + len(program)] = program
    return bytes(data)


def test_post_boot_registers_follow_the_header_checksum():
    assert post_boot_state(rom(b"")).f == 0x80  # checksum 0: H and C clear
    data = bytearray(rom(b""))
    data[0x014D] = 0x01
    state = post_boot_state(bytes(data))
    assert (state.a, state.f, state.pc, state.sp, state.if_) == (0x01, 0xB0, 0x0100, 0xFFFE, 0x01)


def test_bank_register_switches_the_upper_rom_window():
    data = bytearray(4 * 0x4000)
    for bank in range(4):
        data[bank * 0x4000 + 5] = 0x10 + bank
    harness = Harness(bytes(data))
    assert harness.read(0x4005) == 0x11  # bank 1 at reset
    harness.write(0x2000, 3)
    assert harness.read(0x4005) == 0x13
    harness.write(0x2000, 0)  # bank 0 selects bank 1
    assert harness.read(0x4005) == 0x11
    assert harness.read(0x0005) == 0x10  # the lower window is fixed


def test_serial_transfer_completes_after_eight_bits_and_raises_the_interrupt():
    harness = Harness(rom(b""))
    harness.write(0xFF01, ord("A"))
    harness.write(0xFF02, 0x81)
    assert harness.read(0xFF02) & 0x80 and not harness.serial_text
    for _ in range(SERIAL_CYCLES):
        harness.idle(0)
    assert harness.serial_text == b"A"
    assert harness.read(0xFF02) & 0x80 == 0 and harness.read(0xFF01) == 0xFF
    assert harness.cpu.if_ & 0x08 and harness.read(0xFF0F) == 0xE0 | harness.cpu.if_


def test_div_counts_every_64_m_cycles_and_resets_on_write():
    harness = Harness(rom(b""))
    harness.write(0xFF04, 0)
    start = harness.cycles
    while harness.cycles - start < 64:
        harness.idle(0)
    assert harness.read(0xFF04) == 1
    harness.write(0xFF04, 0x55)
    assert harness.read(0xFF04) == 0


def test_run_stops_on_jump_to_self_and_on_the_mooneye_result():
    result = Harness(rom(b"\x00\x18\xfe")).run()
    assert result.reason == "jump to self" and result.instructions == 1
    program = bytes([0x06, 3, 0x0E, 5, 0x16, 8, 0x1E, 13, 0x26, 21, 0x2E, 34, 0x40])
    assert Harness(rom(program)).run().mooneye_passed
    failing = bytes([0x06, 0x42, 0x0E, 0x42, 0x16, 0x42, 0x1E, 0x42, 0x26, 0x42, 0x2E, 0x42, 0x40])
    result = Harness(rom(failing)).run()
    assert result.reason == "ld b,b" and not result.mooneye_passed


def test_an_ordinary_ld_b_b_does_not_stop_the_run():
    result = Harness(rom(b"\x40\x40\x18\xfe")).run()
    assert result.reason == "jump to self" and result.instructions == 2


def test_run_reports_a_locked_cpu_and_the_budget():
    assert Harness(rom(b"\xd3")).run().reason == "locked"
    result = Harness(rom(bytes([0x00, 0xC3, 0x00, 0x01]))).run(max_cycles=1000)
    assert result.reason == "budget"
