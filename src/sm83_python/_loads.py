"""Load, store, stack and high-page instructions: LD, LDH, PUSH, POP.

Each handler runs after the opcode fetch and performs the M-cycles GBCTR lists between the
fetch and the next instruction's fetch (docs/timing.md), each with the address the CPU drives.
"""

from __future__ import annotations

from sm83_python._core import CoreMixin, pack
from sm83_python._flags import FLAG_C, FLAG_H

HIGH_PAGE = 0xFF00


def signed(byte: int) -> int:
    """A byte as a signed offset."""
    return byte - 0x100 if byte & 0x80 else byte


class LoadMixin(CoreMixin):
    def _op_ld_r_r(self, op: int) -> None:
        """LD r,r' -- copy a register; one M-cycle, the fetch (GBCTR LD_r_r)."""
        self._set_r8(op >> 3 & 7, self._get_r8(op & 7))

    def _op_ld_r_n(self, op: int) -> None:
        """LD r,n -- immediate byte into a register (GBCTR LD_r_n)."""
        self._set_r8(op >> 3 & 7, self._read_pc())

    def _op_ld_r_hl(self, op: int) -> None:
        """LD r,(HL) -- load from the address in HL (GBCTR LD_r_hl)."""
        self._set_r8(op >> 3 & 7, self._read(self.hl))

    def _op_ld_hl_r(self, op: int) -> None:
        """LD (HL),r -- store a register at the address in HL (GBCTR LD_hl_r)."""
        self._write(self.hl, self._get_r8(op & 7))

    def _op_ld_hl_n(self, op: int) -> None:
        """LD (HL),n -- store an immediate byte at HL (GBCTR LD_hl_n)."""
        value = self._read_pc()
        self._write(self.hl, value)

    def _op_ld_a_bc_de(self, op: int) -> None:
        """LD A,(BC)/LD A,(DE) -- load A through BC or DE (GBCTR LD_a_bc, LD_a_de)."""
        self.a = self._read(self.de if op & 0x10 else self.bc)

    def _op_ld_bc_de_a(self, op: int) -> None:
        """LD (BC),A/LD (DE),A -- store A through BC or DE (GBCTR LD_bc_a, LD_de_a)."""
        self._write(self.de if op & 0x10 else self.bc, self.a)

    def _op_ld_a_hl_step(self, op: int) -> None:
        """LD A,(HL+)/LD A,(HL-) -- load A, the IDU moves HL (GBCTR LD_a_hli, LD_a_hld)."""
        step = -1 if op & 0x10 else 1  # $2A increments, $3A decrements
        self.a = self._read(self.hl, step)
        self.hl = (self.hl + step) & 0xFFFF

    def _op_ld_hl_step_a(self, op: int) -> None:
        """LD (HL+),A/LD (HL-),A -- store A, the IDU moves HL (GBCTR LD_hli_a, LD_hld_a)."""
        step = -1 if op & 0x10 else 1  # $22 increments, $32 decrements
        self._write(self.hl, self.a, step)
        self.hl = (self.hl + step) & 0xFFFF

    def _op_ld_rr_nn(self, op: int) -> None:
        """LD rr,nn -- 16-bit immediate into BC, DE, HL or SP (GBCTR LD_rr_nn)."""
        self._set_rr(op >> 4 & 3, self._read_pc_word())

    def _op_ld_a_nn(self, op: int) -> None:
        """LD A,(nn) -- load A from an absolute address (GBCTR LD_a_nn)."""
        self.a = self._read(self._read_pc_word())

    def _op_ld_nn_a(self, op: int) -> None:
        """LD (nn),A -- store A at an absolute address (GBCTR LD_nn_a)."""
        self._write(self._read_pc_word(), self.a)

    def _op_ld_nn_sp(self, op: int) -> None:
        """LD (nn),SP -- store SP little-endian at nn and nn+1 (GBCTR LD_nn_sp)."""
        address = self._read_pc_word()
        self._write(address, self.sp & 0xFF, 1)  # the IDU steps WZ to the high byte's address
        self._write((address + 1) & 0xFFFF, self.sp >> 8)  # (GBCTR C5: data row, not labels)

    def _op_ld_sp_hl(self, op: int) -> None:
        """LD SP,HL -- SP takes HL; the internal cycle drives HL (GBCTR LD_sp_hl)."""
        self._idle(self.hl)
        self.sp = self.hl

    def _op_ld_hl_sp_e(self, op: int) -> None:
        """LD HL,SP+e -- HL = SP plus a signed byte; low-byte flags (GBCTR LD_hl_sp_e)."""
        offset = self._read_pc()
        self._idle(0x0000)  # the ALU finishes the high byte; nothing is driven (GBCTR: $0000)
        self.hl = (self.sp + signed(offset)) & 0xFFFF
        # Z = N = 0; H and C come from the unsigned add of the low bytes (Pan Docs)
        self.f = (FLAG_H if (self.sp & 0xF) + (offset & 0xF) > 0xF else 0) | (
            FLAG_C if (self.sp & 0xFF) + offset > 0xFF else 0
        )

    def _op_ldh_n_a(self, op: int) -> None:
        """LDH (n),A -- store A in the high page at $FF00+n (GBCTR LDH_n_a)."""
        self._write(0xFF00 | self._read_pc(), self.a)

    def _op_ldh_a_n(self, op: int) -> None:
        """LDH A,(n) -- load A from the high page at $FF00+n (GBCTR LDH_a_n)."""
        self.a = self._read(0xFF00 | self._read_pc())

    def _op_ldh_c_a(self, op: int) -> None:
        """LDH (C),A -- store A at $FF00+C (GBCTR LDH_c_a)."""
        self._write(0xFF00 | self.c, self.a)

    def _op_ldh_a_c(self, op: int) -> None:
        """LDH A,(C) -- load A from $FF00+C (GBCTR LDH_a_c)."""
        self.a = self._read(0xFF00 | self.c)

    def _op_push(self, op: int) -> None:
        """PUSH rr -- push BC, DE, HL or AF (GBCTR PUSH_rr)."""
        self._push_word((self.bc, self.de, self.hl, self.af)[op >> 4 & 3])

    def _op_pop(self, op: int) -> None:
        """POP rr -- pop BC, DE, HL or AF; POP AF drops F's low nibble (GBCTR POP_rr; U1)."""
        value = self._pop_word()
        match op >> 4 & 3:
            case 0:
                self.bc = value
            case 1:
                self.de = value
            case 2:
                self.hl = value
            case _:
                self.af = value  # the af setter keeps only F bits 7..4


__all__ = ["HIGH_PAGE", "LoadMixin", "pack", "signed"]
