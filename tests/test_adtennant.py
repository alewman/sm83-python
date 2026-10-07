"""Rung 1, second detector: adtennant ``sm83-test-data`` v2 (registers and RAM only).

Provenance unknown (validation.md): the generator is not stated, so this is a detector of last
resort, used for registers and memory only. The corpus assumes decode-execute-prefetch: the
initial PC is one past the opcode and the final PC is one past the *next* opcode, so the core
starts at ``initial pc - 1`` and its final PC is the corpus's minus one. STOP, HALT, EI and DI
are not in the corpus.
"""

import json
from pathlib import Path

import pytest

from sm83_python import SM83, CPUState

CORPUS = Path(__file__).resolve().parents[1] / "reference" / "src" / "sm83-test-data" / "v2"
FILES = sorted(CORPUS.glob("*.json"))
REGISTERS = ("a", "b", "c", "d", "e", "f", "h", "l", "sp")

pytestmark = pytest.mark.skipif(
    not FILES, reason="run scripts/fetch_references.py to fetch the corpus"
)


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_registers_and_ram(path):
    memory = bytearray(0x10000)
    cpu = SM83(memory.__getitem__, memory.__setitem__)
    failures = []
    for case in json.loads(path.read_text()):
        initial, final = case["initial"], case["final"]
        memory[:] = bytes(0x10000)
        for address, value in initial["ram"]:
            memory[address] = value
        cpu.restore_state(
            CPUState(
                **{name: initial[name] for name in REGISTERS},
                pc=initial["pc"] - 1,
                ie=memory[0xFFFF],  # the core owns $FFFF; the corpus treats it as RAM
            )
        )
        cpu.step()
        state = cpu.capture_state()
        wrong = [n for n in REGISTERS if getattr(state, n) != final[n]]
        if state.pc != final["pc"] - 1:
            wrong.append("pc")
        wrong += [f"[{a:#x}]" for a, v in final["ram"] if memory[a] != v]
        if wrong:
            failures.append(f"{case['name']}: {wrong}")
    assert not failures, f"{len(failures)} cases\n" + "\n".join(failures[:8])
