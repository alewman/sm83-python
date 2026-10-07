"""Deterministic processor-boundary traces: JSON Lines I/O and incremental comparison.

The schema is the family's (docs/trace-schema.md) with the SM83's units: ``m_cycles`` where
the Z80 has ``t_states``, and ``accesses`` carrying every M-cycle as
``[kind, address, value, idu]`` with kind ``read``, ``write`` or ``internal`` (value ``null``
for internal) and the IDU direction. Two cores that produce equal traces for the same program
and host are, as far as software can tell, the same CPU.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, fields
from itertools import zip_longest
from typing import TextIO

from sm83_python.debug import Access, BoundaryKind, DebugSession, StepRecord
from sm83_python.disasm import Instruction, disassemble_bytes
from sm83_python.state import CPUState

TraceValue = int | bool | str | tuple[str, ...] | None
TRACE_SCHEMA_VERSION = 1
_MISSING = object()
_STATE_FIELDS = tuple(field.name for field in fields(CPUState))


@dataclass(frozen=True, slots=True)
class TraceDifference:
    """One unequal observation within an aligned trace position."""

    path: str
    left: TraceValue
    right: TraceValue

    def __post_init__(self) -> None:
        if type(self.path) is not str or not self.path:
            raise ValueError("path must be a non-empty string")
        if self.left == self.right:
            raise ValueError("a trace difference must contain unequal values")

    def as_dict(self) -> dict[str, TraceValue]:
        return {"path": self.path, "left": self.left, "right": self.right}


@dataclass(frozen=True, slots=True)
class TraceDivergence:
    """All differences at one aligned processor-boundary position."""

    position: int
    left: StepRecord | None
    right: StepRecord | None
    differences: tuple[TraceDifference, ...]

    def __post_init__(self) -> None:
        if type(self.position) is not int or self.position < 0:
            raise ValueError("position must be a non-negative integer")
        if not self.differences:
            raise ValueError("differences must not be empty")

    def as_dict(self) -> dict[str, object]:
        """Compact deterministic evidence without embedding whole states."""
        return {
            "position": self.position,
            "left_sequence": None if self.left is None else self.left.sequence,
            "right_sequence": None if self.right is None else self.right.sequence,
            "differences": [difference.as_dict() for difference in self.differences],
        }


def _append(out: list[TraceDifference], path: str, left: TraceValue, right: TraceValue) -> None:
    if left != right:
        out.append(TraceDifference(path, left, right))


def _access_texts(accesses: tuple[Access, ...]) -> tuple[str, ...]:
    return tuple(
        f"{kind} {address:04X}={'--' if value is None else f'{value:02X}'} idu={idu:+d}"
        for kind, address, value, idu in accesses
    )


def compare_step_records(left: StepRecord, right: StepRecord) -> tuple[TraceDifference, ...]:
    """Compare two aligned records, ignoring session sequence numbers. Bus accesses are
    compared only when both records carry them."""
    if type(left) is not StepRecord or type(right) is not StepRecord:
        raise TypeError("left and right must be StepRecord values")
    out: list[TraceDifference] = []
    _append(out, "kind", left.kind.value, right.kind.value)
    if left.instruction is None or right.instruction is None:
        _append(
            out,
            "instruction",
            None if left.instruction is None else "present",
            None if right.instruction is None else "present",
        )
    else:
        a, b = left.instruction, right.instruction
        _append(out, "instruction.address", a.address, b.address)
        _append(out, "instruction.data", a.data.hex(), b.data.hex())
        _append(out, "instruction.mnemonic", a.mnemonic, b.mnemonic)
        _append(out, "instruction.operands", a.operands, b.operands)
    _append(out, "m_cycles", left.m_cycles, right.m_cycles)
    for prefix, a_state, b_state in (
        ("before", left.before, right.before),
        ("after", left.after, right.after),
    ):
        if a_state != b_state:
            for name in _STATE_FIELDS:
                _append(out, f"{prefix}.{name}", getattr(a_state, name), getattr(b_state, name))
    if left.accesses is not None and right.accesses is not None:
        _append(out, "accesses", _access_texts(left.accesses), _access_texts(right.accesses))
    return tuple(out)


def iter_trace_divergences(
    left: Iterable[StepRecord], right: Iterable[StepRecord]
) -> Iterator[TraceDivergence]:
    """Yield unequal aligned positions lazily until both traces end (aligned by position)."""
    for position, (a, b) in enumerate(zip_longest(left, right, fillvalue=_MISSING)):
        if a is _MISSING:
            yield TraceDivergence(position, None, b, (TraceDifference("record", None, "present"),))
        elif b is _MISSING:
            yield TraceDivergence(position, a, None, (TraceDifference("record", "present", None),))
        else:
            differences = compare_step_records(a, b)
            if differences:
                yield TraceDivergence(position, a, b, differences)


def first_trace_divergence(
    left: Iterable[StepRecord], right: Iterable[StepRecord]
) -> TraceDivergence | None:
    """The first unequal aligned position, or ``None`` for equal traces."""
    return next(iter_trace_divergences(left, right), None)


def iter_session_steps(session: DebugSession, *, max_steps: int) -> Iterator[StepRecord]:
    """Yield a finite number of live session boundaries without buffering them."""
    if not isinstance(session, DebugSession):
        raise TypeError("session must be a DebugSession")
    if type(max_steps) is not int or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")
    for _ in range(max_steps):
        yield session.step()


def first_session_divergence(
    left: DebugSession, right: DebugSession, *, max_steps: int
) -> TraceDivergence | None:
    """Advance two sessions in lockstep until they differ or the finite budget ends."""
    return first_trace_divergence(
        iter_session_steps(left, max_steps=max_steps),
        iter_session_steps(right, max_steps=max_steps),
    )


# ----- JSON Lines ---------------------------------------------------------------------------


def step_record_to_dict(record: StepRecord) -> dict[str, object]:
    """The versioned JSON-compatible representation of one record."""
    if type(record) is not StepRecord:
        raise TypeError("record must be a StepRecord")
    instruction = record.instruction
    encoded: dict[str, object] = {
        "version": TRACE_SCHEMA_VERSION,
        "sequence": record.sequence,
        "kind": record.kind.value,
        "m_cycles": record.m_cycles,
        "instruction": None
        if instruction is None
        else {
            "address": instruction.address,
            "data": instruction.data.hex(),
            "mnemonic": instruction.mnemonic,
            "operands": list(instruction.operands),
        },
        "before": {name: getattr(record.before, name) for name in _STATE_FIELDS},
        "after": {name: getattr(record.after, name) for name in _STATE_FIELDS},
    }
    if record.accesses is not None:
        encoded["accesses"] = [list(access) for access in record.accesses]
    return encoded


def _object(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return value


def _keys(value: dict[str, object], name: str, expected: set[str]) -> None:
    if set(value) != expected:
        raise ValueError(
            f"{name} fields do not match schema "
            f"(missing={sorted(expected - set(value))}, unknown={sorted(set(value) - expected)})"
        )


def _state(value: object, name: str) -> CPUState:
    encoded = _object(value, name)
    _keys(encoded, name, set(_STATE_FIELDS))
    try:
        return CPUState(**encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {name} CPU state: {exc}") from exc


def _instruction(value: object) -> Instruction | None:
    """Decode a record's instruction; derive its text from the bytes if ``mnemonic`` is
    omitted, so a port in another language never has to reproduce this formatting."""
    if value is None:
        return None
    encoded = _object(value, "instruction")
    if set(encoded) not in ({"address", "data"}, {"address", "data", "mnemonic", "operands"}):
        _keys(encoded, "instruction", {"address", "data", "mnemonic", "operands"})
    try:
        data = bytes.fromhex(encoded["data"])  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("instruction.data must be a hexadecimal string") from exc
    address = encoded["address"]
    if "mnemonic" not in encoded:
        derived = disassemble_bytes(data, address)  # type: ignore[arg-type]
        if derived.data != data:
            raise ValueError(f"instruction.data {data.hex()!r} is not exactly one instruction")
        return derived
    operands = encoded["operands"]
    if type(operands) is not list or not all(type(item) is str for item in operands):
        raise ValueError("instruction.operands must be a list of strings")
    return Instruction(address, data, encoded["mnemonic"], tuple(operands))  # type: ignore[arg-type]


def step_record_from_dict(value: object) -> StepRecord:
    """Reconstruct one strictly validated record from its versioned representation."""
    root = _object(value, "record")
    required = {"version", "sequence", "kind", "m_cycles", "instruction", "before", "after"}
    _keys(root, "record", required | ({"accesses"} & set(root)))
    if type(root["version"]) is not int or root["version"] != TRACE_SCHEMA_VERSION:
        raise ValueError(f"unsupported trace schema version: {root['version']!r}")
    try:
        kind = BoundaryKind(root["kind"])
    except ValueError as exc:
        raise ValueError(f"unsupported boundary kind: {root['kind']!r}") from exc
    accesses = None
    if "accesses" in root:
        raw = root["accesses"]
        if type(raw) is not list or not all(type(a) is list and len(a) == 4 for a in raw):
            raise ValueError("accesses must be a list of [kind, address, value, idu] entries")
        accesses = tuple((k, address, data, idu) for k, address, data, idu in raw)
    return StepRecord(
        sequence=root["sequence"],  # type: ignore[arg-type]
        kind=kind,
        before=_state(root["before"], "before"),
        after=_state(root["after"], "after"),
        m_cycles=root["m_cycles"],  # type: ignore[arg-type]
        instruction=_instruction(root["instruction"]),
        accesses=accesses,
    )


def write_trace(records: Iterable[StepRecord], stream: TextIO) -> int:
    """Write records incrementally as deterministic JSON Lines; returns the count."""
    count = 0
    for record in records:
        encoded = json.dumps(step_record_to_dict(record), separators=(",", ":"), sort_keys=True)
        stream.write(f"{encoded}\n")
        count += 1
    return count


def read_trace(stream: TextIO) -> Iterator[StepRecord]:
    """Yield strictly validated records lazily from a JSON Lines text stream."""
    for line_number, line in enumerate(stream, start=1):
        if not line.strip():
            continue
        try:
            yield step_record_from_dict(json.loads(line))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid trace record at line {line_number}: {exc}") from exc


__all__ = [
    "TRACE_SCHEMA_VERSION",
    "TraceDifference",
    "TraceDivergence",
    "TraceValue",
    "compare_step_records",
    "first_session_divergence",
    "first_trace_divergence",
    "iter_session_steps",
    "iter_trace_divergences",
    "read_trace",
    "step_record_from_dict",
    "step_record_to_dict",
    "write_trace",
]
