"""The command debugger and the ``python -m sm83_python`` runner."""

import io

import pytest

from sm83_python import SM83, CPUState
from sm83_python.__main__ import main
from sm83_python.console import CommandDebugger, CommandError, parse_number
from sm83_python.debug import DebugSession

PROGRAM = bytes([0x3E, 0x07, 0xCD, 0x10, 0x01, 0x3C, 0x18, 0xFE]) + bytes(8) + bytes([0x3C, 0xC9])


def debugger(program: bytes = PROGRAM) -> CommandDebugger:
    memory = bytearray(0x10000)
    memory[0x100 : 0x100 + len(program)] = program
    cpu = SM83(memory.__getitem__, memory.__setitem__)
    cpu.restore_state(CPUState(pc=0x100, sp=0xFFFE))
    return CommandDebugger(DebugSession(cpu, peek_byte=memory.__getitem__, track_accesses=True))


def lines(d: CommandDebugger, command: str) -> list[str]:
    return list(d.execute(command).lines)


def test_numbers():
    assert parse_number("42") == 42 and parse_number("0x2A") == 42 and parse_number("$2a") == 42
    with pytest.raises(CommandError):
        parse_number("-1")
    with pytest.raises(CommandError):
        parse_number("0x10000", maximum=0xFFFF)
    with pytest.raises(CommandError):
        parse_number("zz")


def test_registers_disassemble_and_memory():
    d = debugger()
    assert "PC=0100" in lines(d, "registers")[1]
    assert lines(d, "d 0x100 2") == ["0100  3e07    LD A,$07", "0102  cd1001  CALL $0110"]
    assert lines(d, "memory 0x100 4") == ["0100  3E 07 CD 10"]


def test_step_over_runs_a_call_through_to_its_return():
    d = debugger()
    d.execute("step")
    out = lines(d, "over")
    assert any("CALL" in line for line in out)
    assert "PC=0105" in out[-1]  # back after the CALL, the subroutine already run
    assert d.session.target.capture_state().a == 8


def test_break_continue_watch_and_history():
    d = debugger()
    assert lines(d, "break 0x105") == ["breakpoint at 0105"]
    out = lines(d, "continue")
    assert out[0].startswith("breakpoint") and "PC=0105" in out[-1]
    assert lines(d, "breakpoints") == ["break 0105"]
    lines(d, "delete 0x105")
    assert lines(d, "breakpoints") == ["none"]
    assert lines(d, "watch 0xFFFD w") == ["watchpoint at FFFD"]
    assert lines(d, "unwatch 0xFFFD") == []
    assert lines(d, "history 2")[-1].startswith("#")


def test_set_and_int():
    d = debugger()
    assert "BC=1234" in lines(d, "set bc 0x1234")[0]
    lines(d, "set af 0xFFFF")
    assert d.session.cpu.af == 0xFFF0  # F's low nibble does not exist
    lines(d, "set f 0xFF")
    assert d.session.cpu.f == 0xF0
    assert "IF=04" in lines(d, "int 2")[1]
    with pytest.raises(CommandError):
        d.execute("int 5")
    with pytest.raises(CommandError):
        d.execute("set zz 1")


def test_errors_and_quit():
    d = debugger()
    for bad in ("frobnicate", "break", "run", "watch 1 x", "memory", "step 0", "delete"):
        with pytest.raises(CommandError):
            d.execute(bad)
    assert d.execute("").lines == () and d.execute("quit").quit
    assert d.execute("help").lines[0].startswith("help")


def test_interact_loop_reports_errors_and_stops_on_quit():
    d = debugger()
    out = io.StringIO()
    d.interact(io.StringIO("registers\nbogus\nquit\nregisters\n"), out)
    text = out.getvalue()
    assert "PC=0100" in text and "error: unknown command" in text and text.count("PC=0100") == 1


# ----- python -m sm83_python -------------------------------------------------


def rom(tmp_path, program: bytes):
    data = bytearray(0x8000)
    data[0x100 : 0x100 + len(program)] = program
    path = tmp_path / "t.gb"
    path.write_bytes(bytes(data))
    return str(path)


def test_cli_runs_a_rom_and_prints_serial_text(tmp_path, capsys):
    # LD A,'H' ; LDH ($01),A ; LD A,$81 ; LDH ($02),A ; wait for the transfer ; JR $
    program = bytes(
        [
            0x3E,
            0x48,
            0xE0,
            0x01,
            0x3E,
            0x81,
            0xE0,
            0x02,
            0xF0,
            0x02,
            0xCB,
            0x7F,
            0x20,
            0xFA,
            0x18,
            0xFE,
        ]
    )
    assert main([rom(tmp_path, program)]) == 1  # no "Passed": a failing status
    captured = capsys.readouterr()
    assert captured.out.strip() == "H" and "jump to self" in captured.err


def test_cli_exit_status_for_mooneye_pass_and_trace_file(tmp_path, capsys):
    ok = bytes([0x06, 3, 0x0E, 5, 0x16, 8, 0x1E, 13, 0x26, 21, 0x2E, 34, 0x40])
    trace = tmp_path / "out.jsonl"
    assert main([rom(tmp_path, ok), "--trace", str(trace)]) == 0
    assert "mooneye PASS" in capsys.readouterr().err
    assert len(trace.read_text().splitlines()) == 6


def test_cli_debug_batch_mode(tmp_path, capsys):
    assert (
        main([rom(tmp_path, b"\x00\x00\x76"), "--debug", "--batch", "-c", "step 2", "-c", "quit"])
        == 0
    )
    out = capsys.readouterr().out
    assert "sm83> step 2" in out and "sm83> quit" in out


def test_cli_rejects_a_bad_boot_rom(tmp_path):
    boot = tmp_path / "boot.bin"
    boot.write_bytes(b"\x00" * 10)
    with pytest.raises(SystemExit):
        main([rom(tmp_path, b""), "--boot", str(boot)])
