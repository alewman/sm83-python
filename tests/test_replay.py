"""The MAME replay engine on hand-built traces, and end to end when MAME is installed.

The unit tests build MAME-format lines for tiny programs so each rule of the replay is checked
without MAME: register and cycle comparison, I/O reads answered in order, an interrupt MAME
took raised just before dispatch, and a divergence being reported where it is injected.
The slow test records a real trace with scripts/mame_trace.py --io and replays it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sm83_python.replay import parse_trace, replay

ROOT = Path(__file__).resolve().parents[1]
REGS = "1 B0 0 13 0 D8 1 4D FFFE"  # A F B C D E H L SP, as MAME prints them (hex)


def rom(program: bytes, extra: dict[int, bytes] | None = None) -> bytes:
    data = bytearray(0x8000)
    data[0x100 : 0x100 + len(program)] = program
    for address, content in (extra or {}).items():
        data[address : address + len(content)] = content
    return bytes(data)


def line(pc: int, regs: str, ie: int, if_: int, cycles: int) -> str:
    return f"{pc:X} {regs} {ie:X} {if_:X} {cycles}"


def run(program: bytes, trace: list[str], **kwargs):
    header = ["﻿some MAME message", "SB 41 5"]  # noise before the cartridge entry
    boot = [line(0x00, REGS, 0, 1, 0)]  # a boot ROM line, before PC = $0100
    lines = parse_trace([*header, *boot, *trace])
    image = program if len(program) >= 0x8000 else rom(program)
    return replay(image, lines, **kwargs)


def test_parser_starts_at_the_cartridge_entry_and_attaches_io_reads():
    text = [
        "garbage",
        line(0x00FE, REGS, 0, 1, 0),
        line(0x100, REGS, 0, 1, 100),
        "R FF44 91 104",
        "R FF80 AA 104",  # HRAM: not an I/O read, left to the core's own RAM
        "R FFFF 0 104",
        "SB 41 105",
        line(0x102, REGS, 0, 1, 108),
    ]
    first, second = parse_trace(text)
    assert (first.pc, first.cycles, first.reads) == (0x100, 100, [(0xFF44, 0x91), (0xFFFF, 0)])
    assert second.pc == 0x102 and second.reads == []


def test_a_correct_run_with_an_io_read_passes():
    program = bytes([0x3E, 0x12, 0xF0, 0x44, 0x18, 0xFE])  # LD A,$12 ; LDH A,($44) ; JR $
    trace = [
        line(0x100, REGS, 0, 1, 1000),
        line(0x102, REGS.replace("1 B0", "12 B0", 1), 0, 1, 1008),
        "R FF44 91 1012",
        line(0x104, REGS.replace("1 B0", "91 B0", 1), 0, 1, 1020),
    ]
    result = run(program, trace)
    assert result.ok and result.compared == 2


def test_a_register_difference_is_reported_where_it_happens():
    program = bytes([0x3E, 0x12, 0x00])
    trace = [
        line(0x100, REGS, 0, 1, 1000),
        line(0x102, REGS.replace("1 B0", "13 B0", 1), 0, 1, 1008),
    ]
    result = run(program, trace)
    assert result.divergence and result.divergence.position == 0
    assert result.divergence.problems == ("A = 12, MAME 13",)
    assert "LD A,$12" in result.divergence.describe()


def test_cycle_modes():
    program = bytes([0x00, 0x00])
    trace = [line(0x100, REGS, 0, 1, 1000), line(0x101, REGS, 0, 1, 1008)]  # NOP billed 2 M
    strict = run(program, trace)
    assert strict.divergence.problems == ("1 M-cycles, MAME 2",)
    reported = run(program, trace, cycles="report")
    assert reported.ok and reported.cycle_mismatches == 1 and "MAME 2" in reported.cycle_notes[0]
    assert run(program, trace, cycles="off").ok
    with pytest.raises(ValueError, match="cycles"):
        run(program, trace, cycles="sometimes")


def test_io_read_order_and_address_are_checked():
    program = bytes([0xF0, 0x44, 0x00])  # LDH A,($44)
    wrong_address = [line(0x100, REGS, 0, 1, 0), "R FF45 91 4", line(0x102, REGS, 0, 1, 12)]
    assert "MAME logged FF45" in run(program, wrong_address).divergence.problems[0]
    missing = [line(0x100, REGS, 0, 1, 0), line(0x102, REGS, 0, 1, 12)]
    assert "logged nothing" in run(program, missing).divergence.problems[0]
    extra = [line(0x100, REGS, 0, 1, 0), "R FF44 91 4", "R FF44 91 8", line(0x102, REGS, 0, 1, 12)]
    assert "1 more I/O read" in run(program, extra).divergence.problems[0]


def test_an_interrupt_mame_took_is_raised_and_dispatched_with_the_right_cost():
    # EI ; NOP ; (VBlank taken here) ; handler at $40 is NOP
    program = rom(bytes([0xFB, 0x00, 0x00]), {0x40: bytes([0x00, 0x00])})
    regs_sp = REGS.replace("FFFE", "FFFC")
    trace = [
        line(0x100, REGS, 1, 0, 1000),  # EI: 1 M
        line(0x101, REGS, 1, 0, 1004),  # NOP: 1 M, then the dispatch: 5 M
        line(0x40, regs_sp, 1, 0, 1028),  # the handler's first instruction (a NOP)
        line(0x41, regs_sp, 1, 0, 1032),
    ]
    result = run(program, trace)
    assert result.ok and result.compared == 3 and result.interrupts == 1


def test_the_instruction_after_a_halt_wake_is_not_cycle_checked():
    # HALT ; woken by VBlank (IME = 1 via EI) ; handler JP nn billed one M-cycle short, as MAME does
    program = rom(bytes([0xFB, 0x00, 0x76, 0x00]), {0x40: bytes([0xC3, 0x50, 0x00])})
    regs_sp = REGS.replace("FFFE", "FFFC")
    trace = [
        line(0x100, REGS, 1, 0, 1000),
        line(0x101, REGS, 1, 0, 1004),
        line(0x102, REGS, 1, 0, 1008),  # HALT
        line(0x40, regs_sp, 1, 0, 5000),  # JP $0050, which MAME bills 3 M
        line(0x50, regs_sp, 1, 0, 5012),
    ]
    result = run(program, trace)
    assert result.ok, result.divergence and result.divergence.describe()
    assert result.skipped_cycle_checks == 2


def test_missing_entry_point_is_an_error():
    with pytest.raises(ValueError, match="entry point"):
        replay(rom(b""), parse_trace([line(0x0, REGS, 0, 0, 0)]))


MAME = Path("/usr/games/mame")
BOOT = ROOT / "reference" / "src" / "SameBoy" / "build" / "bin" / "tester" / "dmg_boot.bin"
BLARGG = ROOT / "reference" / "src" / "gb-test-roms" / "cpu_instrs" / "individual" / "06-ld r,r.gb"


@pytest.mark.slow
@pytest.mark.skipif(
    not (MAME.exists() and BOOT.exists() and BLARGG.exists()), reason="needs MAME and the boot ROM"
)
def test_blargg_06_replays_against_a_fresh_mame_trace(tmp_path):
    out = tmp_path / "mame"
    subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / "mame_trace.py"), "gameboy", str(BLARGG),
         "--io", "--seconds", "3", "--out", str(out)],
        check=True, capture_output=True,
    )  # fmt: skip
    result = replay(BLARGG.read_bytes(), parse_trace((out / "error.log").open("rb")))
    assert result.ok, result.divergence and result.divergence.describe()
    assert result.compared > 100_000
    shutil.rmtree(out, ignore_errors=True)
