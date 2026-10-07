#!/usr/bin/env python3
"""Generate the rung 5 test ROM: every opcode, both paths, run identically on the die model and
on the core (docs/validation.md).

Each case sets the registers to known, distinct, writable values, sets the flags so the
requested path of a conditional is taken or not, executes one instruction, and falls or
jumps into the next case. The same ROM runs on Gekkio's VHDL SM83 (scripts/die_run.py) and on
the core; ``scripts/die_compare.py`` compares the two bus sequences cycle for cycle.

Register values (chosen so a driven address names its source): BC = $C190, DE = $C2A5,
HL = $C3B7, SP = $D789, A = $5A. C = $90 so ``LDH A,(C)`` reaches HRAM ($FF90), the only
I/O-page memory the mock SoC has besides IF.

Left out: HALT and STOP (they need a wake-up source the mock SoC lacks) and the 11 undefined
opcodes, which lock the CPU; one is appended at the very end to watch the die do it.

    python scripts/die_programs.py OUT.gb     # also writes OUT.cases.json (the case index)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sm83_python._opcodes import OPCODES  # noqa: E402

BC, DE, HL, SP, A = 0xC190, 0xC2A5, 0xC3B7, 0xD789, 0x5A
RESUME = 0x0070  # RST and interrupt vectors all land here; it jumps to the next case
NEXT_SLOT = 0x80  # HRAM $FF80/$FF81: the address of the next case, for RST and interrupt cases
HOLES = {0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD}
SKIPPED = HOLES | {0x10, 0x76, 0xCB}  # STOP, HALT, and the CB prefix (CB cases are separate)
CONDITIONAL = {"JR_cc", "JP_cc", "CALL_cc", "RET_cc"}

#: (Z, C) flag setups, as the instruction sequence that produces them.
FLAGS = {
    (0, 0): [0x3E, 0x01, 0xB7],  # LD A,1 ; OR A
    (1, 0): [0xAF],  # XOR A
    (0, 1): [0x3E, 0x01, 0xB7, 0x37],  # ... SCF
    (1, 1): [0xAF, 0x37],
}


def ld16(opcode: int, value: int) -> list[int]:
    return [opcode, value & 0xFF, value >> 8]


def condition_flags(code: int, taken: bool) -> tuple[int, int]:
    """(Z, C) that make condition ``code`` (NZ, Z, NC, C) hold (taken) or not."""
    holds = {0: (0, 0), 1: (1, 0), 2: (0, 0), 3: (0, 1)}[code]
    fails = {0: (1, 0), 1: (0, 0), 2: (0, 1), 3: (0, 0)}[code]
    return holds if taken else fails


class Builder:
    """A 32 KiB image with a cursor and the index of the cases placed in it."""

    def __init__(self) -> None:
        self.image = bytearray(0x8000)
        self.at = 0x0150
        self.cases: list[dict] = []
        self.image[0x0100:0x0103] = bytes([0xC3, 0x50, 0x01])  # the boot stub jumps to $0100
        for vector in [*range(0x00, 0x40, 8), *range(0x40, 0x68, 8)]:  # RST and interrupts
            self.image[vector : vector + 3] = bytes([0xC3, RESUME & 0xFF, RESUME >> 8])
        # RESUME: LDH A,(NEXT) ; LD L,A ; LDH A,(NEXT+1) ; LD H,A ; JP HL
        code = [0xF0, NEXT_SLOT, 0x6F, 0xF0, NEXT_SLOT + 1, 0x67, 0xE9]
        self.image[RESUME : RESUME + len(code)] = bytes(code)

    def emit(self, data: list[int]) -> int:
        start = self.at
        self.image[start : start + len(data)] = bytes(data)
        self.at += len(data)
        return start

    def case(self, name, body, *, flags=(1, 0), pre=None, filler=0, align=None, meta=None):
        """Place one case. ``body`` and ``pre`` are byte lists, or functions of the address of
        the case after this one (so a jump can land there); ``filler`` NOPs follow the body.
        ``align`` puts the body's first byte at that low address by padding first."""

        def build(next_address: int) -> tuple[list[int], list[int], list[int]]:
            setup = [
                *ld16(0x31, SP),
                *ld16(0x01, BC),
                *ld16(0x11, DE),
                *ld16(0x21, HL),
                *FLAGS[flags],
                0x3E,
                A,
            ]
            before = pre(next_address) if callable(pre) else list(pre or [])
            instruction = body(next_address) if callable(body) else list(body)
            return setup, before, instruction

        setup, before, instruction = build(0)
        if align is not None:
            while (self.at + len(setup) + len(before)) & 0xFF != align:
                self.emit([0x00])
        next_address = self.at + len(setup) + len(before) + len(instruction) + filler
        setup, before, instruction = build(next_address)
        start = self.emit(setup)
        self.emit(before)
        address = self.emit(instruction)
        self.emit([0x00] * filler)
        self.cases.append(
            {
                "name": name,
                "start": start,
                "address": address,
                "length": len(instruction),
                **(meta or {}),
            }
        )


def push_next(next_address: int) -> list[int]:
    """Push the next case's address (a return address), then restore HL."""
    return [*ld16(0x21, next_address), 0xE5, *ld16(0x21, HL)]


def store_next(next_address: int) -> list[int]:
    """Store the next case's address in HRAM for RESUME, then restore A."""
    return [0x3E, next_address & 0xFF, 0xE0, NEXT_SLOT, 0x3E, next_address >> 8, 0xE0,
            NEXT_SLOT + 1, 0x3E, A]  # fmt: skip


def operand_bytes(opcode: int, category: str) -> list[int]:
    """The operand bytes of an unprefixed opcode (jump targets are patched by the caller)."""
    length = OPCODES[opcode].length
    if length == 1:
        return []
    if category == "LDH_n_a" or category == "LDH_a_n":
        return [0x90]  # HRAM
    if length == 2:
        return [0x11]
    if category in ("LD_nn_a", "LD_a_nn", "LD_nn_sp"):
        return [0x00, 0xC5]  # WRAM
    return [0x34, 0x12]  # LD rr,nn


IE_ON = [0x3E, 0x01, 0xE0, 0xFF]  # LD A,1 ; LDH (IE),A
IF_ON = [0x3E, 0x01, 0xE0, 0x0F]  # LD A,1 ; LDH (IF),A
CLEAN = [0xAF, 0xE0, 0x0F, 0xE0, 0xFF]  # XOR A ; IF = 0 ; IE = 0
INJECT_AFTER = range(-1, 8)  # M-cycles after the HALT's fetch at which the interrupt is raised


def add_halt_case(b: Builder, ime: bool, after: int) -> None:
    """One HALT case: IME on or off, IF bit 0 raised ``after`` M-cycles from the HALT's fetch.

    The mock SoC has no peripheral to raise interrupts, so the case asks the comparison to do
    it (``inject_after``). The request is scheduled relative to a fetch before the HALT, so it
    can precede the HALT's own fetch: ``trigger_offset`` is that instruction's offset in the
    case body and ``trigger_to_halt`` the M-cycles from its fetch to the HALT's.
    """
    enable = [0xFB, 0x00] if ime else []  # EI ; NOP puts IME = 1 before the HALT
    # the instruction before the HALT: NOP (1 M-cycle) after an EI, else LDH (IE),A (3)
    trigger_offset = len(IE_ON) + 1 if ime else len(IE_ON) - 2
    trigger_to_halt = 1 if ime else 3
    meta = {
        "halt_offset": len(IE_ON) + len(enable),
        "trigger_offset": trigger_offset,
        "inject_after": trigger_to_halt + after,
        "mask": 1,
    }
    name = f"HALT ime={int(ime)} IF raised {after:+d} cycles from the fetch"
    b.case(name, [*IE_ON, *enable, 0x76, 0x3C, 0x00], pre=store_next, meta=meta)


def add_pending_halt_cases(b: Builder) -> None:
    """HALT with an interrupt already pending when it executes."""
    b.case("HALT ime=0 pending (the HALT bug)", [*IE_ON, *IF_ON, 0x76, 0x3C, 0x00], pre=store_next)
    b.case("HALT after EI, pending", [*IE_ON, *IF_ON, 0xFB, 0x76, 0x3C, 0x00], pre=store_next)


def build_single(add) -> Builder:
    """A ROM with one scenario and a closing ``JR $``; the die never leaves a halted HALT in
    the mock SoC, so each HALT scenario gets a simulation of its own."""
    b = Builder()
    add(b)
    b.case("end", [0x18, 0xFE])
    return b


def build() -> Builder:
    b = Builder()
    for opcode, entry in enumerate(OPCODES):
        if opcode in SKIPPED:
            continue
        category = entry.category
        paths = ("taken", "not_taken") if category in CONDITIONAL else ("",)
        for path in paths:
            flags = condition_flags(opcode >> 3 & 3, path == "taken") if path else (1, 0)
            name = f"{opcode:02X} {entry.mnemonic}" + (f" [{path}]" if path else "")
            operands = operand_bytes(opcode, category)
            if category in ("JP", "JP_cc", "CALL", "CALL_cc"):
                b.case(name, lambda n, op=opcode: [op, n & 0xFF, n >> 8], flags=flags)
            elif category == "JP_hl":
                b.case(name, [opcode], pre=lambda n: ld16(0x21, n))
            elif category in ("JR", "JR_cc"):
                taken = path != "not_taken"
                # a taken jump skips two NOPs; a jump not taken falls through them
                b.case(name, [opcode, 0x02], flags=flags, filler=2 if taken else 0)
            elif category in ("RET", "RETI", "RET_cc"):
                b.case(name, [opcode], flags=flags, pre=push_next)
            elif category == "RST":
                b.case(name, [opcode], pre=store_next)
            elif category in ("ADD_sp_e", "LD_hl_sp_e"):
                for offset in (0x05, 0xFB):
                    b.case(f"{name} e={offset:#04x}", [opcode, offset], flags=flags)
            else:
                b.case(name, [opcode, *operands], flags=flags)
    for code in range(256):
        b.case(f"CB {code:02X}", [0xCB, code])
    # JR at awkward low addresses (the carry into PCH), forward and backward
    for low in (0x00, 0x7E, 0xFC, 0xFD, 0xFE, 0xFF):
        b.case(f"JR e=+2 at ..{low:02X}", [0x18, 0x02], filler=2, align=low)
    for low in (0x00, 0x80, 0xFB, 0xFE):
        # JR +3 skips to the backward jump JR -5, which lands on the JR +3 that follows the first
        b.case(f"JR e=-5 at ..{low:02X}", [0x18, 0x03, 0x18, 0x03, 0x00, 0x18, 0xFB], align=low)
    # interrupt dispatch from a running program: IE bit, EI, NOP, then IF bit
    for bit in (0, 2, 4):
        mask = 1 << bit
        b.case(
            f"interrupt dispatch bit {bit}",
            [0x3E, mask, 0xE0, 0xFF, 0xFB, 0x00, 0x3E, mask, 0xE0, 0x0F, 0x00],
            pre=store_next,
        )
        b.case("IE cleared", [0xAF, 0xE0, 0xFF])  # IE = 0 again
    b.case("D3 lock", [0xD3])  # the CPU never fetches again
    return b


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    out = Path(sys.argv[1])
    b = build()
    out.write_bytes(bytes(b.image))
    out.with_suffix(".cases.json").write_text(json.dumps(b.cases, indent=1))
    print(f"{len(b.cases)} cases, {b.at - 0x150} bytes of program, wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
