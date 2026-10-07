"""Replay a MAME 0.285 trace of real Game Boy code on the core (validation.md rung 4).

MAME is an emulator-derived detector (docs/mame-oracle.md). Real programs read I/O registers
whose values come from a board the core does not have, so the replay is board-free: every read
of $FF00-$FF7F and $FFFF is answered from MAME's own log (``scripts/mame_trace.py --io``), in
order, and writes to those registers are compared by omission (not obeyed). The core runs the
cartridge ROM and RAM itself, starting from the registers MAME has at PC = $0100.

After each instruction the replay compares ``PC A F B C D E H L SP IE`` with MAME's next line,
and the M-cycles the step took with the difference of MAME's ``totalcycles`` divided by 4
(not across a HALT, whose length the board decides). IF is the board's: it is set from MAME's
line, and an interrupt MAME took (a jump to $40-$60) is raised with ``request_interrupt`` just
before the core would dispatch it. The first divergence is a lead, not a verdict: look it up in
docs/undocumented-behavior.md, then ask a higher tier.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from sm83_python.cpu import SM83, CPUState
from sm83_python.debug import BoundaryKind, next_boundary

START_PC = 0x0100
VECTORS = (0x40, 0x48, 0x50, 0x58, 0x60)
REGISTER_NAMES = ("pc", "a", "f", "b", "c", "d", "e", "h", "l", "sp", "ie")


@dataclass(slots=True)
class Line:
    """One MAME instruction line (state before the instruction) and what it then read."""

    pc: int
    a: int
    f: int
    b: int
    c: int
    d: int
    e: int
    h: int
    l: int  # noqa: E741 - register name
    sp: int
    ie: int
    if_: int
    cycles: int  # MAME totalcycles, T-cycles
    reads: list[tuple[int, int]] = field(default_factory=list)  # I/O reads: (address, data)


def is_io(address: int) -> bool:
    """Reads the replay answers from the log: I/O registers and IE (HRAM is RAM here)."""
    return address <= 0xFF7F or address == 0xFFFF


def parse_trace(lines: Iterable[bytes | str], start_pc: int = START_PC) -> Iterator[Line]:
    """Yield MAME instruction lines from the first one at ``start_pc``, each with the I/O reads
    that followed it. ``SB`` lines and MAME's own messages are skipped."""
    current: Line | None = None
    started = False
    for raw in lines:
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        fields = text.split()
        if len(fields) == 4 and fields[0] == "R":
            if started and current is not None:
                address = int(fields[1], 16)
                if is_io(address):
                    current.reads.append((address, int(fields[2], 16)))
            continue
        if len(fields) != 13:
            continue
        try:
            values = [int(f, 16) for f in fields[:12]] + [int(fields[12])]
        except ValueError:
            continue
        if not started:
            if values[0] != start_pc:
                continue
            started = True
        if current is not None:
            yield current
        current = Line(*values)
    if current is not None:
        yield current


@dataclass(frozen=True, slots=True)
class Divergence:
    """The first place the core and MAME disagree."""

    position: int  # index of the MAME line the replay was executing when it diverged
    line: Line
    problems: tuple[str, ...]
    history: tuple[str, ...]  # the last few instructions, for context

    def describe(self) -> str:
        head = f"divergence at line {self.position}, MAME PC={self.line.pc:04X}"
        return "\n".join([head, *self.problems, "recent:", *self.history])


@dataclass(frozen=True, slots=True)
class ReplayResult:
    compared: int  # MAME lines compared without a difference
    divergence: Divergence | None
    interrupts: int  # dispatches MAME took that the replay raised
    skipped_cycle_checks: int  # groups whose cycle delta was not compared (HALT)
    cycle_notes: tuple[str, ...] = ()  # with cycles="report": the first cycle disagreements
    cycle_mismatches: int = 0

    @property
    def ok(self) -> bool:
        return self.divergence is None


class ReplayHost:
    """ROM (MBC1-style bank register), RAM, and I/O reads answered from the MAME log."""

    def __init__(self, rom: bytes) -> None:
        self.rom = bytes(rom) + bytes(max(0, 0x8000 - len(rom)))
        self.banks = max(1, len(self.rom) // 0x4000)
        self.bank = 1
        self.memory = bytearray(0x10000)
        self.reads: deque[tuple[int, int]] = deque()
        self.problems: list[str] = []
        self.cpu = SM83(self.read, self.write)

    def read(self, address: int) -> int:
        if address < 0x4000:
            return self.rom[address]
        if address < 0x8000:
            return self.rom[self.bank * 0x4000 + address - 0x4000]
        if is_io(address) and address >= 0xFF00:
            if not self.reads or self.reads[0][0] != address:
                expected = f"{self.reads[0][0]:04X}" if self.reads else "nothing"
                self.problems.append(f"core read ${address:04X}, MAME logged {expected}")
                return 0xFF
            return self.reads.popleft()[1]
        return self.memory[address]

    def write(self, address: int, value: int) -> None:
        if address < 0x8000:
            if 0x2000 <= address < 0x4000:
                self.bank = (value & 0x1F or 1) % self.banks
        elif address == 0xFF0F:
            self.cpu.if_ = value & 0x1F  # the board's register, set from MAME's line anyway
        elif not (0xFF00 <= address <= 0xFF7F or address == 0xFFFF):
            self.memory[address] = value  # I/O writes are compared by omission, not obeyed


def _fmt(state: CPUState, text: str) -> str:
    return (
        f"{state.pc:04X} {text:<18} A={state.a:02X} F={state.f:02X} BC={state.b:02X}{state.c:02X} "
        f"DE={state.d:02X}{state.e:02X} HL={state.h:02X}{state.l:02X} SP={state.sp:04X}"
    )


def replay(
    rom: bytes, lines: Iterable[Line], *, limit: int | None = None, cycles: str = "strict"
) -> ReplayResult:
    """Run ``rom`` against MAME's lines; stop at the first divergence or the end/limit.

    ``cycles`` is ``"strict"`` (a cycle disagreement is a divergence), ``"report"`` (collect
    them in the result and carry on) or ``"off"`` (registers and I/O only).
    """
    if cycles not in ("strict", "report", "off"):
        raise ValueError("cycles must be 'strict', 'report' or 'off'")
    from sm83_python.disasm import disassemble

    host = ReplayHost(rom)
    cpu = host.cpu
    peek = _peek(host)
    iterator = iter(lines)
    current = next(iterator, None)
    if current is None:
        raise ValueError("the trace has no line at the cartridge entry point")
    cpu.restore_state(
        CPUState(
            a=current.a, f=current.f & 0xF0, b=current.b, c=current.c, d=current.d, e=current.e,
            h=current.h, l=current.l, sp=current.sp, pc=current.pc, ie=current.ie,
        )
    )  # fmt: skip
    history: deque[str] = deque(maxlen=6)
    halted_cycles = False
    compared = interrupts = skipped = mismatches = 0
    notes: list[str] = []
    for position, following in enumerate(iterator):
        if limit is not None and compared >= limit:
            break
        host.reads = deque(current.reads)
        host.problems = []
        cpu.if_ = current.if_ & 0x1F
        before = cpu.capture_state()
        history.append(_fmt(before, disassemble(peek, before.pc).text))
        used = cpu.step()
        after_halt, halted_cycles = halted_cycles, False
        # An interrupt MAME took, or a HALT it was woken from, happens between two lines.
        for _ in range(8):
            state = cpu.capture_state()
            kind = next_boundary(state)
            took = following.pc in VECTORS and state.pc != following.pc
            if kind is BoundaryKind.HALT_IDLE:
                halted_cycles = True
                enabled = state.ie & 0x1F
                woke = following.if_ & enabled  # still set when MAME woke without dispatching
                if took:  # the source MAME served, plus the higher ones left pending after it
                    woke |= 1 << ((following.pc - 0x40) // 8)
                cpu.if_ |= woke or enabled & -enabled  # else: the lowest enabled source
            elif took and kind is BoundaryKind.INSTRUCTION and state.ime:
                cpu.request_interrupt((following.pc - 0x40) // 8)
                interrupts += 1
            elif kind is not BoundaryKind.DISPATCH:
                break
            used += cpu.step()
        state = cpu.capture_state()
        problems = list(host.problems)
        if host.reads:
            problems.append(
                f"MAME logged {len(host.reads)} more I/O read(s), first ${host.reads[0][0]:04X}"
            )
        for name in REGISTER_NAMES:
            want = getattr(following, name)
            if name == "f":
                want &= 0xF0
            if getattr(state, name) != want:
                problems.append(f"{name.upper()} = {getattr(state, name):X}, MAME {want:X}")
        if halted_cycles or after_halt:
            skipped += 1
        elif cycles != "off":
            delta, remainder = divmod(following.cycles - current.cycles, 4)
            if remainder or delta != used:
                note = f"{used} M-cycles, MAME {(following.cycles - current.cycles) / 4:g}"
                if cycles == "strict":
                    problems.append(note)
                else:
                    mismatches += 1
                    if len(notes) < 20:
                        notes.append(f"line {position} {history[-1]}: {note}")
        if problems:
            return ReplayResult(
                compared,
                Divergence(position, current, tuple(problems), tuple(history)),
                interrupts,
                skipped,
                tuple(notes),
                mismatches,
            )
        compared += 1
        current = following
    return ReplayResult(compared, None, interrupts, skipped, tuple(notes), mismatches)


def _peek(host: ReplayHost):
    """A side-effect-free reader of what the core would fetch (no log consumption)."""

    def peek(address: int) -> int:
        if address < 0x4000:
            return host.rom[address]
        if address < 0x8000:
            return host.rom[host.bank * 0x4000 + address - 0x4000]
        return host.memory[address]

    return peek


def replay_file(
    rom: Path, log: Path, *, limit: int | None = None, cycles: str = "strict"
) -> ReplayResult:
    """Replay a ROM against a MAME ``error.log`` produced by ``scripts/mame_trace.py --io``."""
    with log.open("rb") as stream:
        return replay(rom.read_bytes(), parse_trace(stream), limit=limit, cycles=cycles)


__all__ = [
    "Divergence",
    "Line",
    "ReplayHost",
    "ReplayResult",
    "parse_trace",
    "replay",
    "replay_file",
]
