"""JSON Lines traces: round trip, strict validation, external producers, divergence."""

import io
import json

import pytest

from sm83_python import SM83, CPUState
from sm83_python.debug import DebugSession
from sm83_python.trace import (
    compare_step_records,
    first_session_divergence,
    first_trace_divergence,
    read_trace,
    step_record_from_dict,
    step_record_to_dict,
    write_trace,
)

PROGRAM = bytes([0x3E, 0x05, 0x06, 0x03, 0x80, 0x03, 0xE0, 0x80, 0x18, 0xFE])


def make_session(program: bytes = PROGRAM, tweak=None) -> DebugSession:
    memory = bytearray(0x10000)
    memory[0x100 : 0x100 + len(program)] = program
    cpu = SM83(memory.__getitem__, memory.__setitem__)
    cpu.restore_state(CPUState(pc=0x100, sp=0xFFFE))
    if tweak:
        tweak(cpu, memory)
    return DebugSession(cpu, peek_byte=memory.__getitem__, track_accesses=True)


def records(count: int = 6, **kwargs):
    s = make_session(**kwargs)
    return [s.step() for _ in range(count)]


def test_jsonl_round_trip_is_exact_and_deterministic():
    original = records()
    out = io.StringIO()
    assert write_trace(original, out) == 6
    again = list(read_trace(io.StringIO(out.getvalue())))
    assert again == original
    second = io.StringIO()
    write_trace(again, second)
    assert second.getvalue() == out.getvalue()
    assert out.getvalue().count("\n") == 6


def test_record_dict_carries_cycles_and_idu():
    encoded = step_record_to_dict(records(4)[3])  # INC BC
    assert encoded["version"] == 1 and encoded["kind"] == "instruction"
    assert encoded["m_cycles"] == 2
    assert encoded["accesses"] == [
        ["read", 0x105, 0x03, 1],
        ["internal", 0x0300, None, 1],
    ]  # BC = $0300 after LD B,3
    assert encoded["instruction"]["mnemonic"] == "INC"


def test_an_external_producer_may_omit_the_instruction_text():
    encoded = step_record_to_dict(records(1)[0])
    encoded["instruction"] = {"address": 0x100, "data": "3e05"}
    record = step_record_from_dict(encoded)
    assert record.instruction.text == "LD A,$05"
    encoded["instruction"] = {"address": 0x100, "data": "3e0505"}
    with pytest.raises(ValueError, match="not exactly one instruction"):
        step_record_from_dict(encoded)


@pytest.mark.parametrize(
    "damage",
    [
        lambda d: d.update(version=2),
        lambda d: d.update(kind="nap"),
        lambda d: d.update(extra=1),
        lambda d: d.pop("m_cycles"),
        lambda d: d["before"].pop("pc"),
        lambda d: d["before"].update(f=1),
        lambda d: d.update(accesses=[["read", 0, 0]]),
    ],
)
def test_strict_validation(damage):
    encoded = step_record_to_dict(records(1)[0])
    damage(encoded)
    with pytest.raises(ValueError):
        step_record_from_dict(encoded)


def test_read_trace_reports_the_line_number():
    with pytest.raises(ValueError, match="line 2"):
        list(
            read_trace(io.StringIO(json.dumps(step_record_to_dict(records(1)[0])) + "\nnot json\n"))
        )


def test_equal_traces_do_not_diverge_and_a_changed_program_does_at_the_right_step():
    assert first_trace_divergence(records(), records()) is None
    changed = bytearray(PROGRAM)
    changed[1] = 0x06  # LD A,$06 instead of $05
    divergence = first_trace_divergence(records(), records(program=bytes(changed)))
    assert divergence.position == 0
    paths = {d.path for d in divergence.differences}
    assert {"instruction.data", "after.a"} <= paths


def test_length_mismatch_and_session_lockstep():
    left, right = records(4), records(3)
    divergence = first_trace_divergence(left, right)
    assert divergence.position == 3 and divergence.right is None
    assert first_session_divergence(make_session(), make_session(), max_steps=20) is None

    def poke(cpu, memory):
        cpu.restore_state(CPUState(pc=0x100, sp=0xFFFE, a=1))

    divergence = first_session_divergence(make_session(), make_session(tweak=poke), max_steps=5)
    assert divergence.position == 0 and "before.a" in {d.path for d in divergence.differences}


def test_accesses_are_compared_only_when_both_sides_recorded():
    a = records(1)[0]
    untracked = type(a)(a.sequence, a.kind, a.before, a.after, a.m_cycles, a.instruction, None)
    assert compare_step_records(a, untracked) == ()
