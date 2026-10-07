"""Portable command debugger built as a thin frontend over DebugSession.

``CommandDebugger.execute(line)`` runs one command and returns printable lines;
``interact(input, output)`` is a line-oriented loop with no terminal dependencies.
``python -m sm83_python --debug`` starts one on a ROM. The command set matches the family's
(z80-python, m6800-python) with SM83 registers, IE/IF, and watchpoints that see internal cycles.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import TextIO

from sm83_python.debug import BoundaryKind, DebugSession, RunResult, StepRecord, StopReason
from sm83_python.disasm import ByteReader, Instruction, disassemble
from sm83_python.state import CPUState


class CommandError(ValueError):
    """A malformed or unsupported debugger command."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Rendered lines and control state returned by one debugger command."""

    lines: tuple[str, ...] = ()
    quit: bool = False


_HELP = (
    "help | ?                     Show this command summary",
    "registers | regs | r         Show CPU registers and lifecycle state",
    "step [COUNT] | s             Execute one or more boundaries (ignores breakpoints)",
    "over | o                     Step, running a CALL or RST through to its return",
    "run STEPS [M_CYCLES]         Run with finite step and optional cycle limits",
    "continue | c                 Run up to 1,000,000 steps, off a breakpoint if on one",
    "break ADDRESS | b            Add an execute breakpoint",
    "delete ADDRESS               Remove an execute breakpoint",
    "breakpoints                  List breakpoints and watchpoints",
    "watch ADDRESS [r|w|i|rw...]  Stop after a step with a read, write or internal cycle there",
    "unwatch ADDRESS              Remove a watchpoint",
    "disassemble [ADDRESS] [COUNT] | d  Decode instructions without side effects",
    "memory ADDRESS [LENGTH] | m  Display up to 256 bytes",
    "history [COUNT]              Show retained step records",
    "set REGISTER VALUE           Set A F B C D E H L AF BC DE HL SP PC IE IF",
    "int BIT                      Raise interrupt BIT (0 VBlank .. 4 Joypad) in IF",
    "quit | exit | q              Leave the command loop",
    "Numbers are decimal; 0x1234 or $1234 is hexadecimal.",
)

_REGISTERS = {
    **dict.fromkeys(("A", "F", "B", "C", "D", "E", "H", "L", "IE", "IF"), 0xFF),
    **dict.fromkeys(("AF", "BC", "DE", "HL", "SP", "PC"), 0xFFFF),
}


def parse_number(text: str, name: str = "value", *, maximum: int | None = None) -> int:
    """Parse a debugger number: decimal, or hexadecimal written ``0x1234`` or ``$1234``."""
    try:
        value = int(text[1:], 16) if text.startswith("$") else int(text, 0)
    except ValueError as exc:
        raise CommandError(f"{name} must be an integer") from exc
    if value < 0 or (maximum is not None and value > maximum):
        raise CommandError(
            f"{name} must be in range 0..{maximum}" if maximum else f"{name} must be non-negative"
        )
    return value


def _positive(text: str, name: str) -> int:
    value = parse_number(text, name)
    if value == 0:
        raise CommandError(f"{name} must be positive")
    return value


def _flags(value: int) -> str:
    return "".join(label if value & (0x80 >> i) else "-" for i, label in enumerate("ZNHC"))


def format_state(state: CPUState) -> tuple[str, ...]:
    """Two lines of registers and lifecycle state."""
    return (
        f"AF={state.a:02X}{state.f:02X} BC={state.b:02X}{state.c:02X} "
        f"DE={state.d:02X}{state.e:02X} HL={state.h:02X}{state.l:02X} F={_flags(state.f)}",
        f"PC={state.pc:04X} SP={state.sp:04X} IE={state.ie:02X} IF={state.if_:02X} "
        f"IME={int(state.ime)} EI={int(state.ei_pending)} HALT={int(state.halted)} "
        f"HALTBUG={int(state.halt_bug)} STOP={int(state.stopped)} LOCK={int(state.locked)}",
    )


def format_instruction(instruction: Instruction) -> str:
    return f"{instruction.address:04X}  {instruction.data.hex():<6}  {instruction.text}"


def _format_record(record: StepRecord) -> str:
    where = f"{record.before.pc:04X}"
    what = record.instruction.text if record.instruction else record.kind.value
    return (
        f"#{record.sequence:<6} {where}  {what:<22} {record.m_cycles}M  -> PC={record.after.pc:04X}"
    )


class CommandDebugger:
    """A line-oriented command frontend for one :class:`DebugSession`."""

    def __init__(self, session: DebugSession) -> None:
        if not isinstance(session, DebugSession):
            raise TypeError("session must be a DebugSession")
        self.session = session

    def execute(self, line: str) -> CommandResult:
        """Run one command line; raises :class:`CommandError` if it is malformed."""
        try:
            words = shlex.split(line)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if not words:
            return CommandResult()
        name, args = words[0].lower(), words[1:]
        handlers = {
            ("help", "?"): self._help,
            ("registers", "regs", "r"): self._registers,
            ("step", "s"): self._step,
            ("over", "o"): self._over,
            ("run",): self._run,
            ("continue", "c"): self._continue,
            ("break", "b"): self._break,
            ("delete",): self._delete,
            ("breakpoints",): self._breakpoints,
            ("watch",): self._watch,
            ("unwatch",): self._unwatch,
            ("disassemble", "d"): self._disassemble,
            ("memory", "m"): self._memory,
            ("history",): self._history,
            ("set",): self._set,
            ("int",): self._interrupt,
            ("quit", "exit", "q"): lambda args: CommandResult(quit=True),
        }
        for names, handler in handlers.items():
            if name in names:
                return handler(args)
        raise CommandError(f"unknown command {name!r}; try 'help'")

    def interact(self, source: TextIO, sink: TextIO, prompt: str = "sm83> ") -> None:
        """Read commands from ``source`` until ``quit`` or end of input."""
        for line in source:
            try:
                result = self.execute(line)
            except CommandError as exc:
                print(f"error: {exc}", file=sink)
                continue
            for out in result.lines:
                print(out, file=sink)
            if result.quit:
                return
            print(prompt, end="", file=sink, flush=True)

    # ----- commands ------------------------------------------------------

    def _help(self, args: list[str]) -> CommandResult:
        return CommandResult(_HELP)

    def _state(self) -> CPUState:
        return self.session.target.capture_state()

    def _registers(self, args: list[str]) -> CommandResult:
        return CommandResult(format_state(self._state()))

    def _step(self, args: list[str]) -> CommandResult:
        count = _positive(args[0], "count") if args else 1
        lines = [_format_record(self.session.step()) for _ in range(min(count, 1000))]
        return CommandResult((*lines, *format_state(self._state())))

    def _over(self, args: list[str]) -> CommandResult:
        before = self._state()
        record = self.session.step()
        instruction = record.instruction
        lines = [_format_record(record)]
        if instruction is not None and instruction.mnemonic in ("CALL", "RST"):
            after_call = (instruction.address + instruction.length) & 0xFFFF
            if record.after.pc != after_call and record.after.sp != before.sp:
                result = self._run_until(after_call, before.sp)
                lines.append(self._describe(result))
        return CommandResult((*lines, *format_state(self._state())))

    def _run_until(self, address: int, sp: int) -> RunResult:
        """Run until execution reaches ``address`` with SP back where it was."""
        session = self.session
        steps = 0
        while steps < 1_000_000:
            state = self._state()
            if state.pc == address and state.sp == sp:
                return RunResult(StopReason.BREAKPOINT, steps, steps, 0, state, None)
            if state.pc in session.breakpoints and steps:
                return RunResult(StopReason.BREAKPOINT, steps, steps, 0, state, None)
            session.step()
            steps += 1
        return RunResult(StopReason.STEP_LIMIT, steps, steps, 0, self._state(), None)

    def _describe(self, result: RunResult) -> str:
        text = f"{result.reason.value}: {result.steps} steps, {result.m_cycles} M-cycles"
        if result.hits:
            hit = result.hits[0]
            value = "--" if hit[2] is None else f"{hit[2]:02X}"
            text += f"; {hit[0]} {hit[1]:04X}={value}"
        return text

    def _run(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("run needs a step count")
        steps = _positive(args[0], "steps")
        cycles = _positive(args[1], "m_cycles") if len(args) > 1 else None
        result = self.session.run(max_steps=steps, max_m_cycles=cycles)
        return CommandResult((self._describe(result), *format_state(result.state)))

    def _continue(self, args: list[str]) -> CommandResult:
        session = self.session
        lines: list[str] = []
        if self._state().pc in session.breakpoints:
            lines.append(_format_record(session.step()))
        result = session.run(max_steps=1_000_000)
        return CommandResult((*lines, self._describe(result), *format_state(result.state)))

    def _break(self, args: list[str]) -> CommandResult:
        if len(args) != 1:
            raise CommandError("break needs one address")
        address = parse_number(args[0], "address", maximum=0xFFFF)
        self.session.add_breakpoint(address)
        return CommandResult((f"breakpoint at {address:04X}",))

    def _delete(self, args: list[str]) -> CommandResult:
        if len(args) != 1:
            raise CommandError("delete needs one address")
        self.session.remove_breakpoint(parse_number(args[0], "address", maximum=0xFFFF))
        return CommandResult()

    def _breakpoints(self, args: list[str]) -> CommandResult:
        session = self.session
        lines = [f"break {a:04X}" for a in sorted(session.breakpoints)]
        lines += [f"watch {a:04X} {k}" for a, k in sorted(session.watchpoints.items())]
        return CommandResult(tuple(lines) or ("none",))

    def _watch(self, args: list[str]) -> CommandResult:
        if not 1 <= len(args) <= 2:
            raise CommandError("watch needs an address and an optional r, w, i or rw")
        address = parse_number(args[0], "address", maximum=0xFFFF)
        try:
            self.session.add_watchpoint(address, args[1] if len(args) > 1 else "rw")
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        return CommandResult((f"watchpoint at {address:04X}",))

    def _unwatch(self, args: list[str]) -> CommandResult:
        if len(args) != 1:
            raise CommandError("unwatch needs one address")
        self.session.remove_watchpoint(parse_number(args[0], "address", maximum=0xFFFF))
        return CommandResult()

    def _peek(self) -> ByteReader:
        peek = self.session.peek_byte
        if peek is None:
            raise CommandError("this session has no peek_byte")
        return peek

    def _disassemble(self, args: list[str]) -> CommandResult:
        peek = self._peek()
        address = parse_number(args[0], "address", maximum=0xFFFF) if args else self._state().pc
        count = _positive(args[1], "count") if len(args) > 1 else 8
        lines = []
        for _ in range(min(count, 256)):
            instruction = disassemble(peek, address)
            lines.append(format_instruction(instruction))
            address = (address + instruction.length) & 0xFFFF
        return CommandResult(tuple(lines))

    def _memory(self, args: list[str]) -> CommandResult:
        peek = self._peek()
        if not args:
            raise CommandError("memory needs an address")
        address = parse_number(args[0], "address", maximum=0xFFFF)
        length = _positive(args[1], "length") if len(args) > 1 else 16
        lines = []
        for start in range(address, min(address + length, address + 256), 16):
            row = [peek((start + i) & 0xFFFF) for i in range(min(16, address + length - start))]
            lines.append(f"{start & 0xFFFF:04X}  " + " ".join(f"{b:02X}" for b in row))
        return CommandResult(tuple(lines))

    def _history(self, args: list[str]) -> CommandResult:
        count = _positive(args[0], "count") if args else 10
        records = self.session.history[-count:]
        return CommandResult(tuple(_format_record(r) for r in records) or ("no history",))

    def _set(self, args: list[str]) -> CommandResult:
        if len(args) != 2:
            raise CommandError("set needs a register and a value")
        register = args[0].upper()
        if register not in _REGISTERS:
            raise CommandError(f"unknown register {args[0]!r}")
        value = parse_number(args[1], "value", maximum=_REGISTERS[register])
        cpu = self.session.cpu
        if register == "F":
            value &= 0xF0  # the low nibble of F does not exist
        setattr(cpu, "if_" if register == "IF" else register.lower(), value)
        return CommandResult(format_state(self._state()))

    def _interrupt(self, args: list[str]) -> CommandResult:
        if len(args) != 1:
            raise CommandError("int needs a bit number 0..4")
        bit = parse_number(args[0], "bit", maximum=4)
        self.session.cpu.request_interrupt(bit)
        return CommandResult(format_state(self._state()))


__all__ = [
    "BoundaryKind",
    "CommandDebugger",
    "CommandError",
    "CommandResult",
    "format_instruction",
    "format_state",
    "parse_number",
]
