"""Rotates, shifts, SWAP and single-bit operations: the A-register rotates and the CB page.

``$CB`` is an instruction whose second cycle fetches the CB opcode without an interrupt
check, so CB instructions are uninterruptible two-byte opcodes (SonoSooS "$CB prefix"; U10).
Every CB operation takes the value in and returns the new value, setting its flags.
"""

from __future__ import annotations

from sm83_python._alu import zero_flag
from sm83_python._core import CoreMixin
from sm83_python._flags import FLAG_C, FLAG_H, FLAG_Z


class RotateBitMixin(CoreMixin):
    # ----- the four rotates of A: Z is always cleared ---------------------

    def _rotate_a(self, result: int, carry_out: int) -> None:
        self.a = result & 0xFF
        self.f = FLAG_C if carry_out else 0

    def _op_rlca(self, op: int) -> None:
        """RLCA -- rotate A left; bit 7 goes to C and bit 0 (GBCTR RLCA)."""
        self._rotate_a(self.a << 1 | self.a >> 7, self.a & 0x80)

    def _op_rrca(self, op: int) -> None:
        """RRCA -- rotate A right; bit 0 goes to C and bit 7 (GBCTR RRCA)."""
        self._rotate_a(self.a >> 1 | self.a << 7, self.a & 1)

    def _op_rla(self, op: int) -> None:
        """RLA -- rotate A left through C (GBCTR RLA)."""
        self._rotate_a(self.a << 1 | (1 if self.f & FLAG_C else 0), self.a & 0x80)

    def _op_rra(self, op: int) -> None:
        """RRA -- rotate A right through C (GBCTR RRA)."""
        self._rotate_a(self.a >> 1 | (0x80 if self.f & FLAG_C else 0), self.a & 1)

    # ----- the CB page ----------------------------------------------------

    def _shifted(self, result: int, carry_out: int) -> int:
        """Flags of a CB rotate/shift: Z from the result, N = H = 0, C the bit shifted out."""
        result &= 0xFF
        self.f = zero_flag(result) | (FLAG_C if carry_out else 0)
        return result

    def _cb_rlc(self, value: int) -> int:
        """RLC r/RLC (HL) -- rotate left; bit 7 goes to C and bit 0 (GBCTR RLC_r, RLC_hl)."""
        return self._shifted(value << 1 | value >> 7, value & 0x80)

    def _cb_rrc(self, value: int) -> int:
        """RRC r/RRC (HL) -- rotate right; bit 0 goes to C and bit 7 (GBCTR RRC_r, RRC_hl)."""
        return self._shifted(value >> 1 | value << 7, value & 1)

    def _cb_rl(self, value: int) -> int:
        """RL r/RL (HL) -- rotate left through C (GBCTR RL_r, RL_hl)."""
        return self._shifted(value << 1 | (1 if self.f & FLAG_C else 0), value & 0x80)

    def _cb_rr(self, value: int) -> int:
        """RR r/RR (HL) -- rotate right through C (GBCTR RR_r, RR_hl)."""
        return self._shifted(value >> 1 | (0x80 if self.f & FLAG_C else 0), value & 1)

    def _cb_sla(self, value: int) -> int:
        """SLA r/SLA (HL) -- shift left, bit 0 becomes 0 (GBCTR SLA_r, SLA_hl)."""
        return self._shifted(value << 1, value & 0x80)

    def _cb_sra(self, value: int) -> int:
        """SRA r/SRA (HL) -- arithmetic shift right, bit 7 is kept (GBCTR SRA_r, SRA_hl)."""
        return self._shifted(value >> 1 | value & 0x80, value & 1)

    def _cb_swap(self, value: int) -> int:
        """SWAP r/SWAP (HL) -- exchange the nibbles; C is cleared (GBCTR SWAP_r, SWAP_hl)."""
        return self._shifted(value << 4 | value >> 4, 0)

    def _cb_srl(self, value: int) -> int:
        """SRL r/SRL (HL) -- logical shift right, bit 7 becomes 0 (GBCTR SRL_r, SRL_hl)."""
        return self._shifted(value >> 1, value & 1)

    def _cb_bit(self, bit: int, value: int) -> None:
        """BIT b,r/BIT b,(HL) -- Z = bit b is clear; H set; C kept (GBCTR BIT_b_r, BIT_b_hl)."""
        self.f = (self.f & FLAG_C) | FLAG_H | (0 if value >> bit & 1 else FLAG_Z)

    def _cb_res(self, bit: int, value: int) -> int:
        """RES b,r/RES b,(HL) -- clear bit b; no flags (GBCTR RES_b_r, RES_b_hl)."""
        return value & ~(1 << bit) & 0xFF

    def _cb_set(self, bit: int, value: int) -> int:
        """SET b,r/SET b,(HL) -- set bit b; no flags (GBCTR SET_b_r, SET_b_hl)."""
        return value | (1 << bit)

    def _op_cb(self, op: int) -> None:
        """CB -- prefix: the second byte selects a rotate, shift, BIT, RES or SET (GBCTR CB)."""
        cb = self._read_pc()  # fetched without an interrupt check (U10)
        operation, index = cb >> 3 & 7, cb & 7
        # (HL): BIT reads once; everything else reads then writes
        value = self._read(self.hl) if index == 6 else self._get_r8(index)
        group = cb >> 6
        if group == 1:
            self._cb_bit(operation, value)
            return
        if group == 0:
            result = (
                self._cb_rlc,
                self._cb_rrc,
                self._cb_rl,
                self._cb_rr,
                self._cb_sla,
                self._cb_sra,
                self._cb_swap,
                self._cb_srl,
            )[operation](value)
        elif group == 2:
            result = self._cb_res(operation, value)
        else:
            result = self._cb_set(operation, value)
        if index == 6:
            self._write(self.hl, result)
        else:
            self._set_r8(index, result)


__all__ = ["RotateBitMixin"]
