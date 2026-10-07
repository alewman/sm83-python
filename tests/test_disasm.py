"""Disassembly: known encodings, and every opcode decodes to the table's length."""

import pytest

from sm83_python import SM83
from sm83_python._opcodes import CB_OPCODES, OPCODES
from sm83_python.disasm import disassemble, disassemble_bytes


@pytest.mark.parametrize(
    ("data", "text"),
    [
        (b"\x00", "NOP"),
        (b"\x01\x34\x12", "LD BC,$1234"),
        (b"\x20\xfe", "JR NZ,$0100"),
        (b"\x18\x05", "JR $0107"),
        (b"\xe0\x12", "LDH ($FF12),A"),
        (b"\xf2", "LDH A,(C)"),
        (b"\xe8\xfb", "ADD SP,-5"),
        (b"\xf8\x05", "LD HL,SP+5"),
        (b"\xc7", "RST $00"),
        (b"\xff", "RST $38"),
        (b"\xcb\x46", "BIT 0,(HL)"),
        (b"\xcb\x37", "SWAP A"),
        (b"\xd3", "DB $D3"),
        (b"\xfa\x00\xc0", "LD A,($C000)"),
        (b"\x08\x00\xc0", "LD ($C000),SP"),
        (b"\x22", "LD (HL+),A"),
        (b"\x80", "ADD B"),
        (b"\xc6\x10", "ADD $10"),
        (b"\xc9", "RET"),
    ],
)
def test_text(data, text):
    assert disassemble_bytes(data, 0x0100).text == text


def test_every_opcode_has_the_tables_length():
    for code, entry in enumerate(OPCODES):
        if code == 0xCB:  # the prefix: the table says 1, the decoded instruction is 2 bytes
            continue
        instruction = disassemble_bytes(bytes([code, 0x12, 0x34]), 0)
        expected = 1 if entry.category == "undefined" else entry.length
        assert instruction.length == expected, f"${code:02X} {entry.mnemonic}"
        assert instruction.data[0] == code


def test_every_cb_opcode_decodes():
    for code in range(256):
        instruction = disassemble_bytes(bytes([0xCB, code]), 0)
        assert instruction.length == 2
        assert instruction.text == CB_OPCODES[code].mnemonic


def test_reads_wrap_at_the_top_of_the_address_space():
    memory = {0xFFFF: 0x01, 0x0000: 0x34, 0x0001: 0x12}
    instruction = disassemble(lambda a: memory.get(a, 0), 0xFFFF)
    assert instruction.text == "LD BC,$1234" and instruction.length == 3


def test_disassembly_agrees_with_what_the_core_executes():
    """Instruction length vs PC advance, for every straight-line instruction."""
    skip = {"JP", "JR", "CALL", "RET", "RETI", "RST", "DB", "STOP", "HALT"}
    for code in range(256):
        instruction = disassemble_bytes(bytes([code, 0x12, 0x34]), 0x0200)
        if instruction.mnemonic in skip or code == 0xCB:
            continue
        memory = bytearray(0x10000)
        memory[0x0200:0x0203] = bytes([code, 0x12, 0x34])
        cpu = SM83(memory.__getitem__, memory.__setitem__)
        cpu.pc = 0x0200
        cpu.step()
        assert cpu.pc == 0x0200 + instruction.length, f"${code:02X} {instruction.text}"
