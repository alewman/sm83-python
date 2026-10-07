"""Run SingleStepTests ``sm83`` cases against the core (validation.md rung 1).

Each case gives initial and final registers, sparse RAM and one ``[address, data, "rwm"]``
sample per M-cycle, the opcode fetch first. The corpus is emulator-derived (Ares through
JSMoo), so it is a detector: reads and writes are compared in address, data and order;
internal cycles by kind only, because the corpus writes the previous address there where
GBCTR writes the IDU's (contradiction C1, resolved by the bus-schedule test); ``ie`` is
ignored and ``ei`` is compared on the final state (C4).
"""

from __future__ import annotations

import json
from pathlib import Path

from sm83_python import SM83, CPUState

CORPUS = Path(__file__).resolve().parents[1] / "reference" / "src" / "sm83" / "v1"
#: HALT and STOP are recorded as three plain cycles by the corpus's generator (C3).
EXCLUDED = ("10", "76")
REGISTERS = ("a", "b", "c", "d", "e", "f", "h", "l", "pc", "sp")


def corpus_files() -> list[Path]:
    """Every corpus file the gate covers, in opcode order."""
    return sorted(p for p in CORPUS.glob("*.json") if p.stem not in EXCLUDED)


def kind_of(flags: str) -> str:
    """The cycle kind a corpus ``rwm`` flag string records."""
    return "read" if flags[0] == "r" else "write" if flags[1] == "w" else "internal"


class Bench:
    """A 64 KiB RAM host that records every bus callback of a step."""

    def __init__(self) -> None:
        self.memory = bytearray(0x10000)
        self.log: list[tuple[str, int, int | None]] = []
        self.cpu = SM83(self.read, self.write, self.idle)

    def read(self, address: int) -> int:
        value = self.memory[address]
        self.log.append(("read", address, value))
        return value

    def write(self, address: int, value: int) -> None:
        self.memory[address] = value
        self.log.append(("write", address, value))

    def idle(self, address: int) -> None:
        self.log.append(("internal", address, None))


def run_case(bench: Bench, case: dict) -> list[str]:
    """Run one case; return the list of disagreements (empty when it passes)."""
    initial, final = case["initial"], case["final"]
    memory = bench.memory
    for address, value in initial["ram"]:
        memory[address] = value
    bench.log.clear()
    cpu = bench.cpu
    cpu.restore_state(
        CPUState(
            **{name: initial[name] for name in REGISTERS},
            ime=bool(initial["ime"]),
            # The core owns $FFFF and reads it back as IE; the corpus treats it as RAM and
            # ignores its own `ie` field, so IE starts as whatever the case has at $FFFF.
            ie=dict(initial["ram"]).get(0xFFFF, 0),
        )
    )
    problems: list[str] = []
    cycles = cpu.step()
    if cycles != len(bench.log):
        problems.append(f"step() returned {cycles} but made {len(bench.log)} callbacks")
    expected = [(kind_of(flags), address, data) for address, data, flags in case["cycles"]]
    for index, (want, got) in enumerate(zip(expected, bench.log, strict=False)):
        if want[0] != got[0] or (want[0] != "internal" and want[1:] != got[1:]):
            problems.append(f"cycle {index + 1}: expected {want}, got {got}")
    if len(expected) != len(bench.log):
        problems.append(f"{len(bench.log)} cycles, expected {len(expected)}")
    state = cpu.capture_state()
    problems.extend(
        f"{name}: {getattr(state, name):#x} != {final[name]:#x}"
        for name in REGISTERS
        if getattr(state, name) != final[name]
    )
    if state.ime != bool(final["ime"]):
        problems.append(f"ime: {state.ime} != {bool(final['ime'])}")
    if state.ei_pending != bool(final.get("ei", 0)):
        problems.append(f"ei: {state.ei_pending} != {bool(final.get('ei', 0))}")
    wanted = dict(final["ram"])
    for address, value in wanted.items():
        if memory[address] != value:
            problems.append(f"[{address:#06x}] = {memory[address]:#x}, expected {value:#x}")
    for kind, address, _ in bench.log:
        if kind == "write" and address not in wanted:
            problems.append(f"unexpected write to {address:#06x}")
    for address in {a for a, _ in initial["ram"]} | set(wanted) | {a for _, a, _ in bench.log}:
        memory[address] = 0
    return problems


def run_file(path: Path, limit: int | None = None) -> list[str]:
    """Run a corpus file (or its first ``limit`` cases); return ``name: problem`` lines."""
    bench = Bench()
    failures: list[str] = []
    for case in json.loads(path.read_text())[:limit]:
        failures.extend(f"{case['name']}: {p}" for p in run_case(bench, case))
    return failures
