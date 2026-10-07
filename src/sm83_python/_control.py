"""Control flow and processor state: JP, JR, CALL, RET, RST, DI, EI, NOP, HALT, STOP.

The 11 unused opcodes also live here: they lock the CPU, which never fetches again (U3).
"""

from __future__ import annotations

from collections.abc import Callable

from sm83_python._core import INTERRUPT_BITS, CoreMixin
from sm83_python._loads import signed
from sm83_python.stop import StopAction, StopResult


class ControlMixin(CoreMixin):
    stop_hook: Callable[[bool], StopResult] | None

    def _op_nop(self, op: int) -> None:
        """NOP -- no operation; one M-cycle, the fetch (GBCTR NOP)."""

    # ----- jumps ----------------------------------------------------------

    def _jump_relative(self) -> None:
        offset = self._read_pc()
        # The ALU adds the offset to PCL while the IDU adjusts PCH for the carry (GBCTR JR "W <-
        # adj PCH"). The address bus carries PCH in its high byte and zero below it: Gekkio's
        # die model drives $2400 for a JR whose operand fetch left PC = $2402 (rung 5, all 14
        # JR cases at 10 low addresses, forward and backward).
        self._idle(self.pc & 0xFF00)
        self.pc = (self.pc + signed(offset)) & 0xFFFF

    def _op_jr(self, op: int) -> None:
        """JR e -- relative jump by a signed byte (GBCTR JR)."""
        self._jump_relative()

    def _op_jr_cc(self, op: int) -> None:
        """JR cc,e -- relative jump if the condition holds (GBCTR JR_cc)."""
        if self._condition(op >> 3 & 3):
            self._jump_relative()
        else:
            self._read_pc()  # the operand is still fetched

    def _jump_absolute(self) -> None:
        address = self._read_pc_word()
        self._idle(0x0000)  # PC <- WZ; nothing is driven (GBCTR: $0000)
        self.pc = address

    def _op_jp(self, op: int) -> None:
        """JP nn -- jump to an absolute address (GBCTR JP)."""
        self._jump_absolute()

    def _op_jp_cc(self, op: int) -> None:
        """JP cc,nn -- jump if the condition holds (GBCTR JP_cc)."""
        if self._condition(op >> 3 & 3):
            self._jump_absolute()
        else:
            self._read_pc_word()

    def _op_jp_hl(self, op: int) -> None:
        """JP HL -- jump to HL; the next fetch is the instruction's own last cycle (GBCTR JP_hl)."""
        self.pc = self.hl

    # ----- calls and returns ----------------------------------------------

    def _call(self) -> None:
        address = self._read_pc_word()
        self._push_word(self.pc)
        self.pc = address

    def _op_call(self, op: int) -> None:
        """CALL nn -- push the return address and jump (GBCTR CALL)."""
        self._call()

    def _op_call_cc(self, op: int) -> None:
        """CALL cc,nn -- call if the condition holds (GBCTR CALL_cc)."""
        if self._condition(op >> 3 & 3):
            self._call()
        else:
            self._read_pc_word()

    def _return(self) -> None:
        address = self._pop_word()
        self._idle(0x0000)  # PC <- WZ; nothing is driven (GBCTR: $0000)
        self.pc = address

    def _op_ret(self, op: int) -> None:
        """RET -- pop the return address into PC (GBCTR RET)."""
        self._return()

    def _op_reti(self, op: int) -> None:
        """RETI -- RET, and IME is set at once, no delay (GBCTR RETI; Mooneye reti_intr_timing)."""
        self._return()
        self.ime = True

    def _op_ret_cc(self, op: int) -> None:
        """RET cc -- return if the condition holds (GBCTR RET_cc)."""
        self._idle(0x0000)  # the condition check is a cycle of its own
        if self._condition(op >> 3 & 3):
            self._return()

    def _op_rst(self, op: int) -> None:
        """RST n -- push PC and jump to $00, $08 .. $38 (GBCTR RST)."""
        self._push_word(self.pc)
        self.pc = op & 0x38

    # ----- interrupt master enable ----------------------------------------

    def _op_di(self, op: int) -> None:
        """DI -- disable interrupts at once, cancelling a pending EI (GBCTR DI; rapid_di_ei)."""
        self.ime = False
        self.ei_pending = False

    def _op_ei(self, op: int) -> None:
        """EI -- enable interrupts after the next instruction (GBCTR EI; Mooneye ei_sequence)."""
        self.ei_pending = True

    # ----- HALT, STOP and the holes ---------------------------------------

    def _op_halt(self, op: int) -> None:
        """HALT -- stop executing until an interrupt is pending (GBCTR HALT; U4-U6)."""
        if not self.interrupt_pending:
            self.halted = True
        elif self.ime:
            self.pc = (self.pc - 1) & 0xFFFF  # no halt: the dispatch pushes the HALT itself (U6)
        else:
            self.halt_bug = True  # no halt, and the next fetch does not increment PC (U4)

    def _op_stop(self, op: int) -> None:
        """STOP -- the board decides the outcome through the stop hook (timing.md "STOP"; U11)."""
        pending = self.interrupt_pending
        # the default is a 2-byte STOP that stops until IF changes
        result = StopResult(StopAction.STOP) if self.stop_hook is None else self.stop_hook(pending)
        if result.consume_operand:
            self._read_pc()
        match result.action:
            case StopAction.STOP:
                self.stopped = True
                self.stop_if = self.if_ & INTERRUPT_BITS
            case StopAction.HALT:
                self.halted = True
            case StopAction.NOP:
                pass

    def _op_undefined(self, op: int) -> None:
        """ILLEGAL -- the 11 unused opcodes lock the CPU; no further fetch happens (U3)."""
        self.locked = True


__all__ = ["ControlMixin"]
