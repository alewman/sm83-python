"""Public SM83 CPU API.

The host owns memory and every device. It passes ``read_byte(address)``,
``write_byte(address, value)`` and optionally ``idle(address)`` in, calls :meth:`SM83.step`,
and advances its devices **inside** the callbacks: every M-cycle is one callback, in chip
order, internal cycles included, so the host never adds ``step()``'s return value on top.
See docs/handoff-brief.md "The bus contract".
"""

from collections.abc import Callable

from sm83_python._alu import ALUMixin
from sm83_python._control import ControlMixin
from sm83_python._core import CoreMixin
from sm83_python._dispatch import HANDLER_NAMES
from sm83_python._flags import FLAG_C, FLAG_H, FLAG_N, FLAG_Z, Flags
from sm83_python._loads import LoadMixin
from sm83_python._rotate import RotateBitMixin
from sm83_python.state import CPUState
from sm83_python.stop import StopAction, StopResult

ReadByte = Callable[[int], int]
WriteByte = Callable[[int, int], None]
Idle = Callable[[int], None]
StopHook = Callable[[bool], StopResult]

_BUS = ("read_byte", "write_byte")


def _no_idle(address: int) -> None:
    """The default ``idle``: a host that ignores internal cycles still gets correct timing."""


class SM83(ControlMixin, RotateBitMixin, ALUMixin, LoadMixin, CoreMixin):
    """A Sharp SM83 core whose memory is callables supplied by a host.

    ``read_byte(address) -> int`` and ``write_byte(address, value)`` are the memory bus, one
    M-cycle each; ``idle(address)`` is an M-cycle with no access (default: nothing).
    ``cpu.idu`` is +1, -1 or 0 before each callback: what the IDU did to the value on the
    address bus that cycle. A flat host is two arguments::

        memory = bytearray(0x10000)
        cpu = SM83(memory.__getitem__, memory.__setitem__)

    ``ie`` and ``if_`` are attributes of the core, which owns $FFFF; the board raises
    interrupts with :meth:`request_interrupt` and keeps $FF0F on its own map. ``stop`` is the
    hook the board answers a STOP through. A newly constructed CPU has zeroed state.
    """

    def __init__(
        self,
        read_byte: ReadByte,
        write_byte: WriteByte,
        idle: Idle | None = None,
        stop: StopHook | None = None,
    ) -> None:
        for name, bus in zip(_BUS, (read_byte, write_byte), strict=True):
            if not callable(bus):
                raise TypeError(f"{name} must be callable")
        if idle is not None and not callable(idle):
            raise TypeError("idle must be callable")
        if stop is not None and not callable(stop):
            raise TypeError("stop must be callable")
        self.read_byte = read_byte
        self.write_byte = write_byte
        self.idle = idle if idle is not None else _no_idle
        self.stop_hook = stop
        self.idu = 0
        self.pending_at_fetch = False
        self._cycles = 0
        self._table = [getattr(self, name) for name in HANDLER_NAMES]
        self.restore_state(CPUState())

    def reset(self) -> None:
        """Reset the processor: PC = 0, IME = 0, IE = 0, no pending EI, running. The other
        registers keep their values (power-on values are undocumented, docs/start-here.md)."""
        self.pc = 0
        self.ie = 0
        self.ime = False
        self.ei_pending = False
        self.halted = self.halt_bug = self.halt_dispatch = self.stopped = self.locked = False

    def capture_state(self) -> CPUState:
        """The complete CPU-owned state as an immutable value."""
        return CPUState(
            a=self.a,
            f=self.f,
            b=self.b,
            c=self.c,
            d=self.d,
            e=self.e,
            h=self.h,
            l=self.l,
            sp=self.sp,
            pc=self.pc,
            ie=self.ie,
            if_=self.if_,
            ime=self.ime,
            ei_pending=self.ei_pending,
            halted=self.halted,
            halt_bug=self.halt_bug,
            halt_dispatch=self.halt_dispatch,
            stopped=self.stopped,
            locked=self.locked,
            stop_if=self.stop_if,
        )

    def restore_state(self, state: CPUState) -> None:
        """Replace the CPU-owned state with a captured one."""
        self.a, self.f, self.b, self.c = state.a, state.f, state.b, state.c
        self.d, self.e, self.h, self.l = state.d, state.e, state.h, state.l
        self.sp, self.pc = state.sp, state.pc
        self.ie, self.if_ = state.ie, state.if_
        self.ime, self.ei_pending = state.ime, state.ei_pending
        self.halted, self.halt_bug = state.halted, state.halt_bug
        self.halt_dispatch = state.halt_dispatch
        self.stopped, self.locked = state.stopped, state.locked
        self.stop_if = state.stop_if


__all__ = [
    "FLAG_C",
    "FLAG_H",
    "FLAG_N",
    "FLAG_Z",
    "SM83",
    "CPUState",
    "Flags",
    "Idle",
    "ReadByte",
    "StopAction",
    "StopHook",
    "StopResult",
    "WriteByte",
]
