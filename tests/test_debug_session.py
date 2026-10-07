"""DebugSession: stepping, breakpoints, watchpoints on every kind of cycle, history, limits."""

import pytest

from sm83_python import SM83, CPUState
from sm83_python.debug import BoundaryKind, DebugSession, StepRecord, StopReason, next_boundary


def session(program: bytes, at: int = 0x0200, *, track: bool = True, **state):
    memory = bytearray(0x10000)
    memory[at : at + len(program)] = program
    cpu = SM83(memory.__getitem__, memory.__setitem__)
    cpu.restore_state(CPUState(pc=at, sp=0xC100, **state))
    return DebugSession(cpu, peek_byte=memory.__getitem__, track_accesses=track), memory


def test_a_step_record_has_one_access_per_m_cycle_with_kinds_and_idu():
    s, _ = session(bytes([0x03]))  # INC BC: fetch, then an internal cycle at BC with IDU +1
    record = s.step()
    assert record.kind is BoundaryKind.INSTRUCTION and record.instruction.text == "INC BC"
    assert record.m_cycles == 2 and len(record.accesses) == 2
    assert record.accesses == (("read", 0x0200, 0x03, 1), ("internal", 0x0000, None, 1))


def test_untracked_sessions_record_no_accesses_and_reject_watchpoints():
    s, _ = session(bytes([0x00]), track=False)
    assert s.step().accesses is None
    with pytest.raises(ValueError, match="track_accesses"):
        s.add_watchpoint(0x1234)


def test_watchpoints_see_internal_cycles():
    # LD SP,HL drives HL on its internal cycle: a watch on that address with kind "i" fires
    s, _ = session(bytes([0xF9]), h=0xFE, l=0x10)
    s.add_watchpoint(0xFE10, "i")
    result = s.run(max_steps=5)
    assert result.reason is StopReason.WATCHPOINT
    assert result.hits == (("internal", 0xFE10, None, 0),)


def test_watchpoints_on_reads_and_writes():
    s, _ = session(bytes([0x36, 0x7F, 0x7E]), h=0xC0, l=0x00)  # LD (HL),$7F ; LD A,(HL)
    s.add_watchpoint(0xC000, "w")
    assert s.run(max_steps=5).hits == (("write", 0xC000, 0x7F, 0),)
    s.remove_watchpoint(0xC000)
    s.add_watchpoint(0xC000, "r")
    assert s.run(max_steps=5).hits == (("read", 0xC000, 0x7F, 0),)


def test_ffff_reads_are_recorded_as_ie():
    s, memory = session(bytes([0x7E]), h=0xFF, l=0xFF, ie=0x1F)
    memory[0xFFFF] = 0
    assert s.step().accesses[1] == ("read", 0xFFFF, 0x1F, 0)


def test_breakpoints_stop_before_the_instruction():
    s, _ = session(bytes([0x00, 0x00, 0x00]))
    s.add_breakpoint(0x0202)
    result = s.run(max_steps=10)
    assert result.reason is StopReason.BREAKPOINT and result.steps == 2
    assert result.state.pc == 0x0202


def test_run_limits_and_totals():
    s, _ = session(bytes([0x00] * 8))
    assert s.run(max_steps=3).reason is StopReason.STEP_LIMIT
    result = s.run(max_steps=100, max_m_cycles=2)
    assert result.reason is StopReason.CYCLE_LIMIT and result.m_cycles == 2
    assert (s.total_steps, s.total_instructions, s.total_m_cycles) == (5, 5, 5)


def test_halted_stopped_and_locked_idle_boundaries():
    s, _ = session(bytes([0x76]))
    s.step()
    assert next_boundary(s.cpu.capture_state()) is BoundaryKind.HALT_IDLE
    assert s.run(max_steps=5).reason is StopReason.HALTED
    assert s.run(max_steps=3, stop_on_halt=False).steps == 3
    s, _ = session(bytes([0xD3]))
    s.step()
    assert s.run(max_steps=5, stop_on_halt=False).reason is StopReason.LOCKED
    s, _ = session(bytes([0x10, 0x00]))
    s.step()
    assert s.run(max_steps=5).reason is StopReason.STOPPED


def test_dispatch_is_a_five_cycle_boundary():
    s, _ = session(bytes([0x00]), ie=0x01, if_=0x01, ime=True)
    assert next_boundary(s.cpu.capture_state()) is BoundaryKind.DISPATCH
    record = s.step()
    assert record.kind is BoundaryKind.DISPATCH and record.m_cycles == 5 == len(record.accesses)
    assert record.instruction is None and record.after.pc == 0x40


def test_history_is_bounded_and_close_restores_the_bus():
    memory = bytearray(0x10000)
    cpu = SM83(memory.__getitem__, memory.__setitem__)
    original = cpu.read_byte
    s = DebugSession(cpu, history_limit=2, track_accesses=True)
    assert cpu.read_byte is not original
    for _ in range(4):
        s.step()
    assert [r.sequence for r in s.history] == [2, 3]
    assert [r.sequence for r in s.iter_history(newest_first=True)] == [3, 2]
    s.close()
    assert cpu.read_byte is original and not s.tracking


def test_invalid_arguments():
    s, _ = session(b"\x00")
    with pytest.raises(ValueError):
        s.add_breakpoint(0x10000)
    with pytest.raises(ValueError):
        s.add_watchpoint(0, "x")
    with pytest.raises(ValueError):
        s.run(max_steps=0)
    with pytest.raises(TypeError):
        DebugSession(object())


def test_step_record_validates_itself():
    with pytest.raises(ValueError):
        StepRecord(0, BoundaryKind.INSTRUCTION, CPUState(), CPUState(), 0, None)
    with pytest.raises(ValueError, match="one access per M-cycle"):
        StepRecord(
            0, BoundaryKind.INSTRUCTION, CPUState(), CPUState(), 2, None, (("read", 0, 0, 1),)
        )
