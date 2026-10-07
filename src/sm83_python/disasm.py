"""Side-effect-free SM83 disassembly, driven by the generated opcode table.

Text follows GBCTR's mnemonics (``ADD n``, ``LDH (n),A``, ``RST 0x10``) with operands filled
in: immediates as ``$12`` / ``$1234``, ``LDH`` as the high-page address ``($FF12)``, a relative
jump as its target address, and the signed offsets of ``ADD SP,e`` and ``LD HL,SP+e`` as
``+5`` / ``-3``. The 11 undefined opcodes print as ``DB $XX`` and are one byte long, since the
CPU locks on them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sm83_python._opcodes import CB_OPCODES, OPCODES

ByteReader = Callable[[int], int]


@dataclass(frozen=True, slots=True)
class Instruction:
    """One decoded instruction: where it is, its bytes, and its text."""

    address: int
    data: bytes
    mnemonic: str
    operands: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.address) is not int or not 0 <= self.address <= 0xFFFF:
            raise ValueError("address must be an integer in range 0x0000..0xFFFF")
        if type(self.data) is not bytes or not 1 <= len(self.data) <= 3:
            raise ValueError("data must be 1 to 3 bytes")

    @property
    def length(self) -> int:
        return len(self.data)

    @property
    def text(self) -> str:
        """The instruction as one line, e.g. ``JR NZ,$0123``."""
        return f"{self.mnemonic} {','.join(self.operands)}" if self.operands else self.mnemonic


def _signed(byte: int) -> int:
    return byte - 0x100 if byte & 0x80 else byte


def _operand(token: str, data: bytes, address: int) -> str:
    """Fill one GBCTR operand token (``n``, ``nn``, ``e``, ``(n)``, ``SP+e``...) from ``data``."""
    match token:
        case "n":
            return f"${data[1]:02X}"
        case "(n)":
            return f"(${data[1]:02X})"
        case "nn":
            return f"${data[2] << 8 | data[1]:04X}"
        case "(nn)":
            return f"(${data[2] << 8 | data[1]:04X})"
        case "e":  # JR: the target; ADD SP,e is handled by its mnemonic
            return f"${(address + 2 + _signed(data[1])) & 0xFFFF:04X}"
        case "SP+e":
            return f"SP{_signed(data[1]):+d}"
        case _ if token.startswith("0x"):  # RST vectors
            return f"${int(token, 16):02X}"
        case _:
            return token


def disassemble(read: ByteReader, address: int) -> Instruction:
    """Decode the instruction at ``address``, reading bytes through ``read`` (no bus cycles:
    pass the host's memory, not its bus)."""
    opcode = read(address) & 0xFF
    if opcode == 0xCB:
        second = read((address + 1) & 0xFFFF) & 0xFF
        text = CB_OPCODES[second].mnemonic
        data = bytes((opcode, second))
        word, _, rest = text.partition(" ")
        return Instruction(address, data, word, tuple(rest.split(",")) if rest else ())
    entry = OPCODES[opcode]
    length = 1 if entry.category == "undefined" else entry.length
    data = bytes(read((address + i) & 0xFFFF) & 0xFF for i in range(length))
    word, _, rest = entry.mnemonic.partition(" ")
    tokens = rest.split(",") if rest else []
    if word == "ADD" and tokens == ["SP", "e"]:
        operands = ("SP", f"{_signed(data[1]):+d}")
    elif word == "LDH" and "(n)" in tokens:  # the high page: show the address it reaches
        operands = tuple(f"($FF{data[1]:02X})" if t == "(n)" else t for t in tokens)
    else:
        operands = tuple(_operand(token, data, address) for token in tokens)
    return Instruction(address, data, word, operands)


def disassemble_bytes(data: bytes, address: int = 0) -> Instruction:
    """Decode the instruction at the start of ``data`` as if it were at ``address``."""
    padded = bytes(data) + bytes(3)
    return disassemble(
        lambda a: padded[a - address] if 0 <= a - address < len(padded) else 0, address
    )


__all__ = ["ByteReader", "Instruction", "disassemble", "disassemble_bytes"]
