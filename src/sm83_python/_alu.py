"""Arithmetic and logic: the eight A-register ALU operations, INC/DEC, 16-bit adds, DAA.

Flags are Z N H C in F bits 7-4 (Pan Docs CPU_Instruction_Set.md; GBCTR's per-instruction
``flags`` fields). H is the carry out of bit 3 (bit 11 for 16-bit adds); C the carry out of the
top bit; for subtraction they are borrows.
"""

from __future__ import annotations

from sm83_python._core import CoreMixin
from sm83_python._flags import FLAG_C, FLAG_H, FLAG_N, FLAG_Z
from sm83_python._loads import signed


def zero_flag(result: int) -> int:
    return FLAG_Z if result & 0xFF == 0 else 0


class ALUMixin(CoreMixin):
    def _alu_operand(self, op: int) -> int:
        """The source of an A-register ALU opcode: n, (HL) or a register by its encoding."""
        if op & 0xC0 == 0xC0:  # $C6..$FE: immediate operand
            return self._read_pc()
        if op & 7 == 6:  # (HL)
            return self._read(self.hl)
        return self._get_r8(op & 7)

    def _add(self, value: int, carry: int) -> None:
        total = self.a + value + carry
        self.f = (
            zero_flag(total)
            | (FLAG_H if (self.a & 0xF) + (value & 0xF) + carry > 0xF else 0)
            | (FLAG_C if total > 0xFF else 0)
        )
        self.a = total & 0xFF

    def _subtract(self, value: int, carry: int) -> int:
        """A - value - carry with SUB/SBC/CP flags; returns the result without storing it."""
        total = self.a - value - carry
        self.f = (
            FLAG_N
            | zero_flag(total)
            | (FLAG_H if (self.a & 0xF) < (value & 0xF) + carry else 0)
            | (FLAG_C if total < 0 else 0)
        )
        return total & 0xFF

    def _op_add(self, op: int) -> None:
        """ADD A,r/ADD A,(HL)/ADD A,n -- A = A + operand (GBCTR ADD_r, ADD_hl, ADD_n)."""
        self._add(self._alu_operand(op), 0)

    def _op_adc(self, op: int) -> None:
        """ADC A,r/ADC A,(HL)/ADC A,n -- A = A + operand + carry (GBCTR ADC_r, ADC_hl, ADC_n)."""
        self._add(self._alu_operand(op), 1 if self.f & FLAG_C else 0)

    def _op_sub(self, op: int) -> None:
        """SUB r/SUB (HL)/SUB n -- A = A - operand (GBCTR SUB_r, SUB_hl, SUB_n)."""
        self.a = self._subtract(self._alu_operand(op), 0)

    def _op_sbc(self, op: int) -> None:
        """SBC A,r/SBC A,(HL)/SBC A,n -- A = A - operand - carry (GBCTR SBC_r, SBC_hl, SBC_n)."""
        self.a = self._subtract(self._alu_operand(op), 1 if self.f & FLAG_C else 0)

    def _op_and(self, op: int) -> None:
        """AND r/AND (HL)/AND n -- A = A & operand; H is always set (GBCTR AND_r, AND_hl, AND_n)."""
        self.a &= self._alu_operand(op)
        self.f = zero_flag(self.a) | FLAG_H

    def _op_xor(self, op: int) -> None:
        """XOR r/XOR (HL)/XOR n -- A = A ^ operand (GBCTR XOR_r, XOR_hl, XOR_n)."""
        self.a ^= self._alu_operand(op)
        self.f = zero_flag(self.a)

    def _op_or(self, op: int) -> None:
        """OR r/OR (HL)/OR n -- A = A | operand (GBCTR OR_r, OR_hl, OR_n)."""
        self.a |= self._alu_operand(op)
        self.f = zero_flag(self.a)

    def _op_cp(self, op: int) -> None:
        """CP r/CP (HL)/CP n -- compare: SUB's flags, A unchanged (GBCTR CP_r, CP_hl, CP_n)."""
        self._subtract(self._alu_operand(op), 0)

    def _inc8(self, value: int) -> int:
        result = (value + 1) & 0xFF
        # C is untouched; N = 0; H = carry out of bit 3
        self.f = (self.f & FLAG_C) | zero_flag(result) | (FLAG_H if value & 0xF == 0xF else 0)
        return result

    def _dec8(self, value: int) -> int:
        result = (value - 1) & 0xFF
        # C is untouched; N = 1; H = borrow from bit 4
        self.f = (
            (self.f & FLAG_C) | FLAG_N | zero_flag(result) | (FLAG_H if value & 0xF == 0 else 0)
        )
        return result

    def _op_inc_r(self, op: int) -> None:
        """INC r -- increment a register (GBCTR INC_r)."""
        index = op >> 3 & 7
        self._set_r8(index, self._inc8(self._get_r8(index)))

    def _op_dec_r(self, op: int) -> None:
        """DEC r -- decrement a register (GBCTR DEC_r)."""
        index = op >> 3 & 7
        self._set_r8(index, self._dec8(self._get_r8(index)))

    def _op_inc_hl(self, op: int) -> None:
        """INC (HL) -- read-modify-write at HL (GBCTR INC_hl)."""
        value = self._read(self.hl)
        self._write(self.hl, self._inc8(value))

    def _op_dec_hl(self, op: int) -> None:
        """DEC (HL) -- read-modify-write at HL (GBCTR DEC_hl)."""
        value = self._read(self.hl)
        self._write(self.hl, self._dec8(value))

    def _op_inc_rr(self, op: int) -> None:
        """INC rr -- 16-bit increment through the IDU, no flags (GBCTR INC_rr)."""
        index = op >> 4 & 3
        value = self._get_rr(index)
        self._idle(value, 1)  # the internal cycle drives rr while the IDU increments it
        self._set_rr(index, value + 1)

    def _op_dec_rr(self, op: int) -> None:
        """DEC rr -- 16-bit decrement through the IDU, no flags (GBCTR DEC_rr)."""
        index = op >> 4 & 3
        value = self._get_rr(index)
        self._idle(value, -1)
        self._set_rr(index, value - 1)

    def _op_add_hl_rr(self, op: int) -> None:
        """ADD HL,rr -- 16-bit add; Z kept, H is the carry out of bit 11 (GBCTR ADD_hl_rr)."""
        self._idle(0x0000)  # the second byte of the add; nothing is driven (GBCTR: $0000)
        operand = self._get_rr(op >> 4 & 3)
        total = self.hl + operand
        self.f = (
            (self.f & FLAG_Z)
            | (FLAG_H if (self.hl & 0xFFF) + (operand & 0xFFF) > 0xFFF else 0)
            | (FLAG_C if total > 0xFFFF else 0)
        )
        self.hl = total & 0xFFFF

    def _op_add_sp_e(self, op: int) -> None:
        """ADD SP,e -- SP plus a signed byte; flags from the low-byte add (GBCTR ADD_sp_e)."""
        offset = self._read_pc()
        self._idle(0x0000)  # the ALU adds the low byte
        self._idle(0x0000)  # and finishes the high byte
        # Z = N = 0; H and C come from the unsigned add of the low bytes (Pan Docs)
        self.f = (FLAG_H if (self.sp & 0xF) + (offset & 0xF) > 0xF else 0) | (
            FLAG_C if (self.sp & 0xFF) + offset > 0xFF else 0
        )
        self.sp = (self.sp + signed(offset)) & 0xFFFF

    def _op_daa(self, op: int) -> None:
        """DAA -- decimal-adjust A after BCD arithmetic (GBCTR DAA; U2, Mooneye instr/daa)."""
        a = self.a
        carry = self.f & FLAG_C
        if self.f & FLAG_N:  # after a subtraction: undo the borrows, C stays as it was
            if self.f & FLAG_C:
                a -= 0x60
            if self.f & FLAG_H:
                a -= 0x06
        else:  # after an addition: add the missing corrections, and set C past $99
            if self.f & FLAG_C or a > 0x99:
                a += 0x60
                carry = FLAG_C
            if self.f & FLAG_H or self.a & 0x0F > 0x09:
                a += 0x06
        self.a = a & 0xFF
        self.f = (self.f & FLAG_N) | zero_flag(self.a) | carry  # H is always cleared

    def _op_cpl(self, op: int) -> None:
        """CPL -- complement A (GBCTR CPL)."""
        self.a ^= 0xFF
        self.f |= FLAG_N | FLAG_H

    def _op_scf(self, op: int) -> None:
        """SCF -- set the carry flag (GBCTR SCF)."""
        self.f = (self.f & FLAG_Z) | FLAG_C

    def _op_ccf(self, op: int) -> None:
        """CCF -- complement the carry flag (GBCTR CCF)."""
        self.f = (self.f & FLAG_Z) | (self.f & FLAG_C ^ FLAG_C)


__all__ = ["ALUMixin", "zero_flag"]
