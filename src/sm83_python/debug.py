"""Dependency-free execution control and structured debugging records.

``DebugSession`` drives an existing CPU (any object with ``step()`` and ``capture_state()``)
one boundary at a time, with execute breakpoints, bounded runs, a history ring and, optionally,
bus tracking and watchpoints. Tracking records **every M-cycle**, internal cycles included,
each with the address the CPU drove and the IDU direction, so a watchpoint can see the
``INC rr`` / ``PUSH`` / OAM-bug addresses a memory-only view would miss. It never changes what
the core does.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from sm83_python.disasm import ByteReader, Instruction, disassemble
from sm83_python.state import CPUState

INTERRUPT_BITS = 0x1F


@runtime_checkable
class DebugTarget(Protocol):
    """Minimum processor interface consumed by :class:`DebugSession`."""

    def step(self) -> int:
        """Advance one boundary and return the M-cycles consumed."""

    def capture_state(self) -> CPUState:
        """Capture the current CPU-owned state."""


class BoundaryKind(Enum):
    """Kind of work one ``step()`` call starts with."""

    INSTRUCTION = "instruction"
    DISPATCH = "dispatch"  # an interrupt is taken: five M-cycles
    HALT_IDLE = "halt_idle"  # halted: one idle cycle, and a wake-up may dispatch in the same step
    STOP_IDLE = "stop_idle"  # in stop mode: one idle cycle
    LOCKED_IDLE = "locked_idle"  # an undefined opcode locked the CPU: one idle cycle, forever


class StopReason(Enum):
    """Why a bounded run returned control."""

    BREAKPOINT = "breakpoint"  # before the instruction at a breakpoint
    WATCHPOINT = "watchpoint"  # after the step that touched a watched address
    HALTED = "halted"
    STOPPED = "stopped"
    LOCKED = "locked"
    STEP_LIMIT = "step_limit"
    CYCLE_LIMIT = "cycle_limit"


#: One M-cycle as the CPU drove the bus: ``(kind, address, value, idu)``. ``kind`` is
#: ``"read"``, ``"write"`` or ``"internal"``; ``value`` is the byte moved, ``None`` for an
#: internal cycle; ``idu`` is +1, -1 or 0.
Access = tuple[str, int, int | None, int]
_ACCESS_KINDS = frozenset(("read", "write", "internal"))
_WATCH_LETTER = {"r": "read", "w": "write", "i": "internal"}


def _valid_access(access: object) -> bool:
    if type(access) is not tuple or len(access) != 4:
        return False
    kind, address, value, idu = access
    return (
        kind in _ACCESS_KINDS
        and type(address) is int
        and 0 <= address <= 0xFFFF
        and (value is None if kind == "internal" else type(value) is int and 0 <= value <= 0xFF)
        and idu in (-1, 0, 1)
    )


@dataclass(frozen=True, slots=True)
class StepRecord:
    """Immutable before/after evidence for one processor boundary."""

    sequence: int
    kind: BoundaryKind
    before: CPUState
    after: CPUState
    m_cycles: int
    instruction: Instruction | None
    #: Every M-cycle the step made, in order, when the session tracks the bus; ``None`` when
    #: it does not (absent means *not recorded*, not *none*).
    accesses: tuple[Access, ...] | None = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if type(self.kind) is not BoundaryKind:
            raise ValueError("kind must be a BoundaryKind")
        if type(self.before) is not CPUState or type(self.after) is not CPUState:
            raise ValueError("before and after must be CPUState values")
        if type(self.m_cycles) is not int or self.m_cycles <= 0:
            raise ValueError("m_cycles must be a positive integer")
        if self.instruction is not None and type(self.instruction) is not Instruction:
            raise ValueError("instruction must be an Instruction or None")
        if self.kind is not BoundaryKind.INSTRUCTION and self.instruction is not None:
            raise ValueError("only instruction boundaries can contain an instruction")
        if self.accesses is not None and (
            type(self.accesses) is not tuple or not all(map(_valid_access, self.accesses))
        ):
            raise ValueError("accesses must be a tuple of (kind, address, value, idu) or None")
        if self.accesses is not None and len(self.accesses) != self.m_cycles:
            raise ValueError("a tracked step makes exactly one access per M-cycle")


@dataclass(frozen=True, slots=True)
class RunResult:
    """Summary of one bounded run operation."""

    reason: StopReason
    steps: int
    instructions: int
    m_cycles: int
    state: CPUState
    last_record: StepRecord | None
    hits: tuple[Access, ...] = ()  # for WATCHPOINT: the accesses that stopped the run

    def __post_init__(self) -> None:
        if type(self.reason) is not StopReason:
            raise ValueError("reason must be a StopReason")
        for name in ("steps", "instructions", "m_cycles"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.instructions > self.steps:
            raise ValueError("instructions cannot exceed steps")


def next_boundary(state: CPUState) -> BoundaryKind:
    """What the next ``step()`` starts with, decided exactly as ``SM83.step()`` decides it."""
    if state.locked:
        return BoundaryKind.LOCKED_IDLE
    if state.stopped:
        return BoundaryKind.STOP_IDLE
    if state.halted:
        return BoundaryKind.HALT_IDLE
    if state.ime and state.ie & state.if_ & INTERRUPT_BITS:
        return BoundaryKind.DISPATCH
    return BoundaryKind.INSTRUCTION


_IDLE_REASONS = {
    BoundaryKind.HALT_IDLE: StopReason.HALTED,
    BoundaryKind.STOP_IDLE: StopReason.STOPPED,
    BoundaryKind.LOCKED_IDLE: StopReason.LOCKED,
}


class DebugSession:
    """Control an existing CPU host without modifying its execution core.

    ``peek_byte`` must be side-effect-free (the host's memory, not its bus); without it step
    records carry no disassembly. ``track_accesses=True`` wraps the CPU's ``read_byte``,
    ``write_byte`` and ``idle`` to record every M-cycle in :attr:`StepRecord.accesses` and to
    enable watchpoints; :meth:`close` puts the originals back. The target may be a whole board
    whose ``cpu`` attribute is the processor.
    """

    def __init__(
        self,
        target: DebugTarget,
        *,
        peek_byte: ByteReader | None = None,
        history_limit: int = 256,
        track_accesses: bool = False,
    ) -> None:
        if not isinstance(target, DebugTarget):
            raise TypeError("target must provide step() and capture_state()")
        if peek_byte is not None and not callable(peek_byte):
            raise TypeError("peek_byte must be callable or None")
        if type(history_limit) is not int or history_limit < 0:
            raise ValueError("history_limit must be a non-negative integer")
        self.target = target
        self.cpu = getattr(target, "cpu", target)
        self.peek_byte = peek_byte
        self.history_limit = history_limit
        self.breakpoints: set[int] = set()
        #: Watchpoints: address -> a string of ``r`` (read), ``w`` (write), ``i`` (internal).
        self.watchpoints: dict[int, str] = {}
        self.total_steps = 0
        self.total_instructions = 0
        self.total_m_cycles = 0
        self._history: deque[StepRecord] = deque(maxlen=history_limit or 1)
        self._accesses: list[Access] | None = None
        self._originals: tuple | None = None
        if track_accesses:
            self._wrap_bus()

    @property
    def tracking(self) -> bool:
        """Whether this session is recording the bus."""
        return self._originals is not None

    def _wrap_bus(self) -> None:
        cpu = self.cpu
        read_byte, write_byte, idle = cpu.read_byte, cpu.write_byte, cpu.idle
        self._originals = (read_byte, write_byte, idle)
        log: list[Access] = []
        self._accesses = log

        def tracked_read(address: int) -> int:
            value = read_byte(address) & 0xFF
            # the core owns $FFFF and uses IE, whatever the host returned
            log.append(("read", address, cpu.ie if address == 0xFFFF else value, cpu.idu))
            return value

        def tracked_write(address: int, value: int) -> None:
            log.append(("write", address, value & 0xFF, cpu.idu))
            write_byte(address, value)

        def tracked_idle(address: int) -> None:
            log.append(("internal", address, None, cpu.idu))
            idle(address)

        cpu.read_byte, cpu.write_byte, cpu.idle = tracked_read, tracked_write, tracked_idle

    def close(self) -> None:
        """Stop tracking and give the CPU its own bus callables back."""
        if self._originals is not None:
            self.cpu.read_byte, self.cpu.write_byte, self.cpu.idle = self._originals
            self._originals = None
            self._accesses = None

    @property
    def history(self) -> tuple[StepRecord, ...]:
        """Bounded immutable view of the retained step records."""
        return tuple(self._history)

    def clear_history(self) -> None:
        """Discard retained records without changing execution totals."""
        self._history.clear()

    def iter_history(self, *, newest_first: bool = False) -> Iterator[StepRecord]:
        return reversed(self._history) if newest_first else iter(self._history)

    def add_breakpoint(self, address: int) -> None:
        """Stop before executing the instruction at a 16-bit address."""
        self.breakpoints.add(self._validate_address(address))

    def remove_breakpoint(self, address: int) -> None:
        self.breakpoints.discard(self._validate_address(address))

    def add_watchpoint(self, address: int, kind: str = "rw") -> None:
        """Stop after any step with a ``r``(ead), ``w``(rite) and/or ``i``(nternal) cycle at
        ``address``. Internal cycles are the ones the CPU drives with no access."""
        if not self.tracking:
            raise ValueError("watchpoints need a session created with track_accesses=True")
        if not kind or set(kind) - set("rwi") or len(set(kind)) != len(kind):
            raise ValueError('kind must be a combination of "r", "w" and "i"')
        self.watchpoints[self._validate_address(address)] = kind

    def remove_watchpoint(self, address: int) -> None:
        self.watchpoints.pop(self._validate_address(address), None)

    def step(self) -> StepRecord:
        """Advance exactly one boundary, ignoring execute breakpoints."""
        before = self.target.capture_state()
        kind = next_boundary(before)
        instruction = None
        if kind is BoundaryKind.INSTRUCTION and self.peek_byte is not None:
            instruction = disassemble(self.peek_byte, before.pc)
        if self._accesses is not None:
            self._accesses.clear()
        m_cycles = self.target.step()
        if type(m_cycles) is not int or m_cycles <= 0:
            raise ValueError("target step() must return a positive integer M-cycle count")
        record = StepRecord(
            sequence=self.total_steps,
            kind=kind,
            before=before,
            after=self.target.capture_state(),
            m_cycles=m_cycles,
            instruction=instruction,
            accesses=None if self._accesses is None else tuple(self._accesses),
        )
        self.total_steps += 1
        self.total_m_cycles += m_cycles
        if kind is BoundaryKind.INSTRUCTION:
            self.total_instructions += 1
        if self.history_limit:
            self._history.append(record)
        return record

    def run(
        self, *, max_steps: int, max_m_cycles: int | None = None, stop_on_halt: bool = True
    ) -> RunResult:
        """Run until a stop condition or the mandatory finite step budget is reached.

        Execute breakpoints stop before the instruction; watchpoints stop after the step that
        touched the watched address. A locked CPU always stops (it would never leave); a
        halted or stopped one stops unless ``stop_on_halt`` is false. The cycle limit is
        checked after each boundary and may be exceeded by that boundary's cost.
        """
        if type(max_steps) is not int or max_steps <= 0:
            raise ValueError("max_steps must be a positive integer")
        if max_m_cycles is not None and (type(max_m_cycles) is not int or max_m_cycles <= 0):
            raise ValueError("max_m_cycles must be a positive integer or None")
        steps = instructions = cycles = 0
        last: StepRecord | None = None
        while steps < max_steps:
            state = self.target.capture_state()
            kind = next_boundary(state)
            if kind is BoundaryKind.INSTRUCTION and state.pc in self.breakpoints:
                return RunResult(StopReason.BREAKPOINT, steps, instructions, cycles, state, last)
            if kind in _IDLE_REASONS and (stop_on_halt or kind is BoundaryKind.LOCKED_IDLE):
                reason = _IDLE_REASONS[kind]
                return RunResult(reason, steps, instructions, cycles, state, last)
            last = self.step()
            steps += 1
            cycles += last.m_cycles
            instructions += last.kind is BoundaryKind.INSTRUCTION
            hits = self._watch_hits(last)
            if hits:
                return RunResult(
                    StopReason.WATCHPOINT, steps, instructions, cycles, last.after, last, hits
                )
            if max_m_cycles is not None and cycles >= max_m_cycles:
                return RunResult(
                    StopReason.CYCLE_LIMIT, steps, instructions, cycles, last.after, last
                )
        state = last.after if last is not None else self.target.capture_state()
        return RunResult(StopReason.STEP_LIMIT, steps, instructions, cycles, state, last)

    def _watch_hits(self, record: StepRecord) -> tuple[Access, ...]:
        if not self.watchpoints or not record.accesses:
            return ()
        return tuple(
            access
            for access in record.accesses
            if access[1] in self.watchpoints
            and access[0] in {_WATCH_LETTER[c] for c in self.watchpoints[access[1]]}
        )

    @staticmethod
    def _validate_address(address: int) -> int:
        if type(address) is not int or not 0 <= address <= 0xFFFF:
            raise ValueError("address must be an integer in range 0x0000..0xFFFF")
        return address


__all__ = [
    "Access",
    "BoundaryKind",
    "DebugSession",
    "DebugTarget",
    "RunResult",
    "StepRecord",
    "StopReason",
    "next_boundary",
]
