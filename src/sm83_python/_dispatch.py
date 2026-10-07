"""Opcode decoding: bit patterns, first match wins, mapped to handler names.

A pattern is eight characters, ``0`` and ``1`` for fixed bits and ``x`` for a field the
handler decodes itself. The table is built once and checked to cover all 256 opcodes; the
mnemonic text of every opcode is in the generated ``_opcodes.py``. Pan Docs
``CPU_Instruction_Set.md`` gives the four blocks (00xxxxxx, 01xxxxxx, 10xxxxxx, 11xxxxxx).
"""

from __future__ import annotations

#: (pattern, handler method name), most specific first.
RULES: tuple[tuple[str, str], ...] = (
    # block 0: miscellaneous, 16-bit, INC/DEC, LD r,n, rotates of A
    ("00000000", "_op_nop"),
    ("00001000", "_op_ld_nn_sp"),
    ("00010000", "_op_stop"),
    ("00011000", "_op_jr"),
    ("001xx000", "_op_jr_cc"),
    ("00xx0001", "_op_ld_rr_nn"),
    ("00xx1001", "_op_add_hl_rr"),
    ("000x0010", "_op_ld_bc_de_a"),
    ("000x1010", "_op_ld_a_bc_de"),
    ("001x0010", "_op_ld_hl_step_a"),
    ("001x1010", "_op_ld_a_hl_step"),
    ("00xx0011", "_op_inc_rr"),
    ("00xx1011", "_op_dec_rr"),
    ("00110100", "_op_inc_hl"),
    ("00110101", "_op_dec_hl"),
    ("00110110", "_op_ld_hl_n"),
    ("00xxx100", "_op_inc_r"),
    ("00xxx101", "_op_dec_r"),
    ("00xxx110", "_op_ld_r_n"),
    ("00000111", "_op_rlca"),
    ("00001111", "_op_rrca"),
    ("00010111", "_op_rla"),
    ("00011111", "_op_rra"),
    ("00100111", "_op_daa"),
    ("00101111", "_op_cpl"),
    ("00110111", "_op_scf"),
    ("00111111", "_op_ccf"),
    # block 1: LD r,r' with $76 = HALT
    ("01110110", "_op_halt"),
    ("01110xxx", "_op_ld_hl_r"),
    ("01xxx110", "_op_ld_r_hl"),
    ("01xxxxxx", "_op_ld_r_r"),
    # block 2 and the immediate forms: the eight ALU operations
    ("10000xxx", "_op_add"),
    ("11000110", "_op_add"),
    ("10001xxx", "_op_adc"),
    ("11001110", "_op_adc"),
    ("10010xxx", "_op_sub"),
    ("11010110", "_op_sub"),
    ("10011xxx", "_op_sbc"),
    ("11011110", "_op_sbc"),
    ("10100xxx", "_op_and"),
    ("11100110", "_op_and"),
    ("10101xxx", "_op_xor"),
    ("11101110", "_op_xor"),
    ("10110xxx", "_op_or"),
    ("11110110", "_op_or"),
    ("10111xxx", "_op_cp"),
    ("11111110", "_op_cp"),
    # block 3: control flow, stack, high page, CB, interrupts
    ("110xx000", "_op_ret_cc"),
    ("11001001", "_op_ret"),
    ("11011001", "_op_reti"),
    ("11101001", "_op_jp_hl"),
    ("11111001", "_op_ld_sp_hl"),
    ("11xx0001", "_op_pop"),
    ("11xx0101", "_op_push"),
    ("110xx010", "_op_jp_cc"),
    ("11000011", "_op_jp"),
    ("110xx100", "_op_call_cc"),
    ("11001101", "_op_call"),
    ("11xxx111", "_op_rst"),
    ("11100000", "_op_ldh_n_a"),
    ("11110000", "_op_ldh_a_n"),
    ("11100010", "_op_ldh_c_a"),
    ("11110010", "_op_ldh_a_c"),
    ("11101000", "_op_add_sp_e"),
    ("11111000", "_op_ld_hl_sp_e"),
    ("11101010", "_op_ld_nn_a"),
    ("11111010", "_op_ld_a_nn"),
    ("11001011", "_op_cb"),
    ("11110011", "_op_di"),
    ("11111011", "_op_ei"),
    # the 11 holes: $D3 $DB $DD $E3 $E4 $EB $EC $ED $F4 $FC $FD
    ("11010011", "_op_undefined"),
    ("11011011", "_op_undefined"),
    ("11011101", "_op_undefined"),
    ("11100011", "_op_undefined"),
    ("11100100", "_op_undefined"),
    ("11101011", "_op_undefined"),
    ("11101100", "_op_undefined"),
    ("11101101", "_op_undefined"),
    ("11110100", "_op_undefined"),
    ("11111100", "_op_undefined"),
    ("11111101", "_op_undefined"),
)


def matches(pattern: str, opcode: int) -> bool:
    """Whether ``opcode`` fits an eight-character bit pattern."""
    bits = f"{opcode:08b}"
    return all(p in ("x", b) for p, b in zip(pattern, bits, strict=True))


def build_table() -> tuple[str, ...]:
    """The handler method name of each of the 256 opcodes; fails if one has no rule."""
    names = []
    for opcode in range(256):
        for pattern, name in RULES:
            if matches(pattern, opcode):
                names.append(name)
                break
        else:
            raise ValueError(f"no decode rule for opcode ${opcode:02X}")
    return tuple(names)


HANDLER_NAMES = build_table()

__all__ = ["HANDLER_NAMES", "RULES", "build_table", "matches"]
