"""Rung 3: the Mooneye board-free subset in the minimal harness.

Hardware-verified tier: every ROM names the consoles it was verified on (DMG ... AGS). Pass is
B, C, D, E, H, L = 3, 5, 8, 13, 21, 34 at ``LD B,B``. The nine ROMs of validation.md's rung 3
need only ROM, RAM, IF/IE, a completing serial port and DIV; two more pass on the same
harness. Everything that needs TIMA, the PPU or OAM DMA as a clock is rung 6 (the board).
"""

from pathlib import Path

import pytest

from sm83_python.harness import Harness

BASE = next(
    iter((Path(__file__).resolve().parents[1] / "reference" / "roms").glob("mts-*/acceptance")),
    None,
)

#: ROM -> the rule it earns (docs/undocumented-behavior.md item)
ROMS = {
    "instr/daa": "U2 DAA on every input",
    "bits/reg_f": "U1 F's low nibble",
    "interrupts/ie_push": "U8 IE written by the dispatch push",
    "if_ie_registers": "IF/IE register behaviour at the core boundary",
    "ei_sequence": "U9 EI delay",
    "ei_timing": "U9 EI timing",
    "rapid_di_ei": "U9 DI cancels EI",
    "intr_timing": "dispatch takes 5 M-cycles (against DIV)",
    "reti_intr_timing": "U9 RETI enables IME at once",
    "div_timing": "harness DIV model against core cycle counts (not a core claim)",
    "pop_timing": "POP's cycle count and bus order",
}

pytestmark = pytest.mark.skipif(BASE is None, reason="run scripts/fetch_references.py")


@pytest.mark.parametrize("name", ROMS, ids=list(ROMS))
def test_mooneye_passes(name):
    result = Harness((BASE / f"{name}.gb").read_bytes()).run(max_cycles=10_000_000)
    assert result.mooneye_passed, f"{result.reason}, registers {result.registers}"
