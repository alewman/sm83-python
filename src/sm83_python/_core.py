"""Registers, the bus, and the shape of ``step()``: fetch, interrupt dispatch, HALT.

The bus contract (docs/handoff-brief.md "The bus contract"): every M-cycle is one callback,
in chip order, with the address the CPU drives, internal cycles included. ``idu`` holds what
the 16-bit increment/decrement unit did to that address (+1, -1 or 0) while the callback runs.
A step starts with the opcode fetch and ends after the instruction's last execute cycle, so
the next instruction's fetch belongs to the next step (model (a) in docs/start-here.md).
"""

from __future__ import annotations

from collections.abc import Callable

from sm83_python._flags import FLAG_C, FLAG_H, FLAG_N, FLAG_Z

#: Register name for each 3-bit register field of an opcode; index 6 is (HL), not a register.
R8 = ("b", "c", "d", "e", "h", "l", None, "a")

IE_ADDRESS = 0xFFFF
INTERRUPT_BITS = 0x1F


def pack(high: int, low: int) -> int:
    """A 16-bit value from its two bytes."""
    return (high << 8) | low


class CoreMixin:
    """State and plumbing shared by every instruction family."""

    # Declared for the type checker; ``SM83.__init__`` assigns them.
    a: int
    f: int
    b: int
    c: int
    d: int
    e: int
    h: int
    l: int  # noqa: E741 - canonical SM83 register name
    sp: int
    pc: int
    ie: int
    if_: int
    ime: bool
    ei_pending: bool
    halted: bool
    halt_bug: bool
    halt_dispatch: bool
    stopped: bool
    locked: bool
    stop_if: int
    pending_at_fetch: bool
    idu: int
    read_byte: Callable[[int], int]
    write_byte: Callable[[int, int], None]
    idle: Callable[[int], None]
    _cycles: int
    _table: list[Callable[[int], None]]

    # ----- register pairs -------------------------------------------------

    @property
    def af(self) -> int:
        return pack(self.a, self.f)

    @af.setter
    def af(self, value: int) -> None:
        self.a = value >> 8
        self.f = value & 0xF0  # F bits 3..0 do not exist (U1; Mooneye bits/reg_f)

    @property
    def bc(self) -> int:
        return pack(self.b, self.c)

    @bc.setter
    def bc(self, value: int) -> None:
        self.b, self.c = value >> 8, value & 0xFF

    @property
    def de(self) -> int:
        return pack(self.d, self.e)

    @de.setter
    def de(self, value: int) -> None:
        self.d, self.e = value >> 8, value & 0xFF

    @property
    def hl(self) -> int:
        return pack(self.h, self.l)

    @hl.setter
    def hl(self, value: int) -> None:
        self.h, self.l = value >> 8, value & 0xFF

    def _get_r8(self, index: int) -> int:
        """The register named by a 3-bit opcode field (never 6, which is (HL))."""
        return getattr(self, R8[index])

    def _set_r8(self, index: int, value: int) -> None:
        setattr(self, R8[index], value & 0xFF)

    def _get_rr(self, index: int) -> int:
        """BC, DE, HL or SP: the 2-bit pair field of LD rr,nn / INC rr / ADD HL,rr."""
        return (self.bc, self.de, self.hl, self.sp)[index]

    def _set_rr(self, index: int, value: int) -> None:
        setattr(self, ("bc", "de", "hl", "sp")[index], value & 0xFFFF)

    def _condition(self, code: int) -> bool:
        """NZ, Z, NC or C: the 2-bit condition field of JR/JP/CALL/RET cc."""
        flag = FLAG_Z if code < 2 else FLAG_C
        return bool(self.f & flag) == bool(code & 1)

    # ----- the bus: one callback per M-cycle ------------------------------

    def _read(self, address: int, idu: int = 0) -> int:
        """One M-cycle that reads. The core owns $FFFF: its value is ``ie`` (the cycle is
        still made, so watchpoints see it)."""
        self.idu = idu
        self._cycles += 1
        value = self.read_byte(address) & 0xFF
        return self.ie if address == IE_ADDRESS else value

    def _write(self, address: int, value: int, idu: int = 0) -> None:
        """One M-cycle that writes. A write to $FFFF updates ``ie`` before the callback
        returns, so the dispatch's high-byte push can cancel itself (Mooneye ie_push)."""
        self.idu = idu
        self._cycles += 1
        if address == IE_ADDRESS:
            self.ie = value & 0xFF
        self.write_byte(address, value & 0xFF)

    def _idle(self, address: int, idu: int = 0) -> None:
        """One M-cycle with no memory access; ``address`` is what the CPU drives (GBCTR)."""
        self.idu = idu
        self._cycles += 1
        self.idle(address)

    def _read_pc(self) -> int:
        """Operand fetch: read at PC, the IDU increments PC."""
        value = self._read(self.pc, 1)
        self.pc = (self.pc + 1) & 0xFFFF
        return value

    def _read_pc_word(self) -> int:
        """Two operand fetches, low byte first."""
        low = self._read_pc()
        return pack(self._read_pc(), low)

    def _push_word(self, value: int) -> None:
        """PUSH, CALL, RST: internal cycle at SP, then high and low byte below it."""
        self._idle(self.sp, -1)
        self.sp = (self.sp - 1) & 0xFFFF
        self._write(self.sp, value >> 8, -1)
        self.sp = (self.sp - 1) & 0xFFFF
        self._write(self.sp, value & 0xFF)

    def _pop_word(self) -> int:
        """POP, RET: low byte then high byte, the IDU incrementing SP after each read."""
        low = self._read(self.sp, 1)
        self.sp = (self.sp + 1) & 0xFFFF
        high = self._read(self.sp, 1)
        self.sp = (self.sp + 1) & 0xFFFF
        return pack(high, low)

    # ----- interrupts, one step at a time ---------------------------------

    def request_interrupt(self, bit: int) -> None:
        """Raise interrupt ``bit`` (0 VBlank .. 4 Joypad) in IF. May be called from any bus
        callback: it is visible to every decision the core takes after that callback returns,
        never to one already taken earlier in the same step (docs/handoff-brief.md)."""
        if not 0 <= bit <= 4:
            raise ValueError("interrupt bit must be 0..4")
        self.if_ |= 1 << bit

    @property
    def interrupt_pending(self) -> bool:
        """IE & IF has a bit among the five interrupt sources set."""
        return bool(self.ie & self.if_ & INTERRUPT_BITS)

    def _dispatch(self) -> None:
        """Interrupt dispatch, five M-cycles from the discarded fetch to the vector choice
        (docs/timing.md "Interrupt dispatch"; SonoSooS "ISR and NMI"; SameBoy GB_cpu_run).

        The vector is chosen late: IE is sampled after the high-byte push and IF after the low
        one, so a push that writes IE ($FFFF) can cancel the dispatch and send PC to $0000
        (Mooneye ie_push, hardware-verified on every model).
        """
        self.halted = False
        if self.halt_dispatch:
            # EI; HALT with an interrupt pending: the HALT's own M-cycle is the discarded fetch,
            # at the byte after it, with PC not advanced; the IDU then puts PC back onto the
            # HALT itself (die model, rung 5)
            self.halt_dispatch = False
            self._read(self.pc)
            self._idle(self.pc, -1)
            self.pc = (self.pc - 1) & 0xFFFF
        else:
            self._read(self.pc, 1)  # M1: the fetch that would start the next instruction, discarded
            self._idle((self.pc + 1) & 0xFFFF, -1)  # M2: the IDU puts PC back (docs C2)
        self._idle(self.sp, -1)  # M3: SP - 1
        self.sp = (self.sp - 1) & 0xFFFF
        self._write(self.sp, self.pc >> 8, -1)  # M4: PCH
        enabled = self.ie  # IE as the high-byte push left it
        self.sp = (self.sp - 1) & 0xFFFF
        self._write(self.sp, self.pc & 0xFF)  # M5: PCL
        queue = enabled & self.if_ & INTERRUPT_BITS  # IF as the low-byte push left it
        if queue:
            bit = (queue & -queue).bit_length() - 1  # lowest pending bit wins
            self.if_ &= ~(1 << bit)
            self.pc = 0x40 + 8 * bit
        else:
            self.pc = 0x0000  # cancelled: IF untouched (Mooneye ie_push round 1)
        self.ime = False

    def step(self) -> int:
        """Execute one instruction, one interrupt dispatch, or one halted/stopped/locked
        M-cycle. Returns the number of M-cycles consumed, which is the number of bus callbacks
        made. A halted, stopped or locked CPU makes exactly one ``idle(PC)`` and returns 1;
        the board loops."""
        start = self._cycles
        if self.locked:
            self._idle(0x0000)  # the 11 holes: no more fetches, the die drives $0000 (U3, rung 5)
            return 1
        if self.stopped:
            self._idle(self.pc)
            if (self.if_ & INTERRUPT_BITS) != self.stop_if:
                self.stopped = False
            return 1
        effective_ime = self.ime
        if self.ei_pending:  # EI takes effect after the instruction that follows it
            self.ime = True
            self.ei_pending = False
        pending = self.interrupt_pending  # sampled after the previous cycle's callback
        if self.halted:
            self._idle(self.pc)
            if not pending:
                return 1
            self.halted = False
            if not effective_ime:
                return 1  # wake without dispatch: the next step fetches normally
            self._dispatch()
            return self._cycles - start
        if effective_ime and pending:
            self._dispatch()
            return self._cycles - start
        self.pending_at_fetch = pending  # HALT decides on the interrupt state before its own fetch
        opcode = self._read(self.pc, 1)  # the fetch
        if self.halt_bug:
            self.halt_bug = False  # the HALT bug: this fetch does not increment PC (U4)
        else:
            self.pc = (self.pc + 1) & 0xFFFF
        self._table[opcode](opcode)
        return self._cycles - start


__all__ = ["FLAG_C", "FLAG_H", "FLAG_N", "FLAG_Z", "R8", "CoreMixin", "pack"]
