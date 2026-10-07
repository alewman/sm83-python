"""Immutable values for capturing and restoring SM83 processor state."""

from dataclasses import dataclass


def _require_int(name: str, value: object, maximum: int) -> None:
    if type(value) is not int or not 0 <= value <= maximum:
        width = 2 if maximum == 0xFF else 4
        message = f"{name} must be an integer in range 0x{'0' * width}..0x{maximum:0{width}X}"
        raise ValueError(message)


def _require_bool(name: str, value: object) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a bool")


@dataclass(frozen=True, slots=True)
class CPUState:
    """Complete CPU-owned state at an instruction boundary.

    Registers, IE and IF (both live in the core, see docs/handoff-brief.md), IME and the
    delayed-EI flag, and the halted / stopped / locked / HALT-bug conditions. It excludes host
    memory, devices, scheduling and counters, so restoring it restores the processor, not a
    machine. ``f`` keeps only bits 7-4 (the low nibble does not exist).
    """

    a: int = 0
    f: int = 0
    b: int = 0
    c: int = 0
    d: int = 0
    e: int = 0
    h: int = 0
    l: int = 0  # noqa: E741 - canonical SM83 register name
    sp: int = 0
    pc: int = 0
    ie: int = 0
    if_: int = 0
    ime: bool = False
    ei_pending: bool = False
    halted: bool = False
    halt_bug: bool = False
    halt_dispatch: bool = False
    stopped: bool = False
    locked: bool = False
    stop_if: int = 0

    def __post_init__(self) -> None:
        for name in ("a", "b", "c", "d", "e", "h", "l", "ie", "if_", "stop_if"):
            _require_int(name, getattr(self, name), 0xFF)
        _require_int("f", self.f, 0xFF)
        if self.f & 0x0F:
            raise ValueError("f bits 3..0 do not exist and must be 0")
        for name in ("sp", "pc"):
            _require_int(name, getattr(self, name), 0xFFFF)
        for name in (
            "ime",
            "ei_pending",
            "halted",
            "halt_bug",
            "halt_dispatch",
            "stopped",
            "locked",
        ):
            _require_bool(name, getattr(self, name))


__all__ = ["CPUState"]
