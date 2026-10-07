#!/usr/bin/env python3
"""Compare the core's bus with Gekkio's VHDL SM83, cycle for cycle (validation.md rung 5).

Builds the all-opcodes ROM (scripts/die_programs.py), runs it on the core behind a model of
the die testbench's mock SoC, runs it on the die model (scripts/die_run.py), and compares the
two M-cycle sequences from the first fetch at $0100: kind (read, write or internal) and
address always, data for reads and writes. The die is die-traced, so where it and the core
disagree the die decides, unless it also disagrees with a hardware-verified test.

    python scripts/die_compare.py [--work DIR] [--rerun] [--show N]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from die_programs import build  # noqa: E402
from die_run import run_die  # noqa: E402

from sm83_python import SM83, CPUState  # noqa: E402


class MockSoc:
    """The die testbench's memory map: ROM, WRAM, HRAM, IF, LY and SC; the rest floats high."""

    def __init__(self, rom: bytes) -> None:
        self.rom = rom
        self.memory = bytearray(0x10000)
        self.rows: list[tuple[str, int, int | None]] = []
        self.cpu = SM83(self.read, self.write, self.idle)

    def read(self, address: int) -> int:
        if address < 0x8000:
            value = self.rom[address]
        elif address == 0xFF0F:
            value = 0xE0 | self.cpu.if_
        elif address == 0xFF44:
            value = 0x90
        elif address == 0xFF02:
            value = 0x7F
        elif 0xC000 <= address < 0xE000 or address >= 0xFF80:
            value = self.memory[address]
        else:
            value = 0xFF
        self.rows.append(("read", address, value))
        return value

    def write(self, address: int, value: int) -> None:
        if address == 0xFF0F:
            self.cpu.if_ = value & 0x1F
        elif 0xC000 <= address < 0xE000 or address >= 0xFF80:
            self.memory[address] = value
        self.rows.append(("write", address, value))

    def idle(self, address: int) -> None:
        self.rows.append(("internal", address, None))


def run_core(rom: bytes, cases: list[dict]) -> tuple[list[tuple], list[str | None], int]:
    """The core's rows from the first fetch at $0100, each tagged with its case name."""
    soc = MockSoc(rom)
    cpu = soc.cpu
    cpu.restore_state(CPUState(pc=0x0100))
    at_address = {c["address"]: c["name"] for c in cases}
    lock_address = max(c["address"] for c in cases)
    tags: list[str | None] = []
    current = None
    while not cpu.locked:
        current = at_address.get(cpu.pc, current if cpu.pc not in at_address else None)
        before = len(soc.rows)
        cpu.step()
        tags.extend([current] * (len(soc.rows) - before))
        if cpu.pc > lock_address + 4 and not cpu.locked:
            raise RuntimeError("ran past the last case without locking")
    for _ in range(40):  # the locked CPU keeps making idle cycles; the die's are compared too
        before = len(soc.rows)
        cpu.step()
        tags.extend([current] * (len(soc.rows) - before))
    return soc.rows, tags, len(soc.rows)


def read_die(path: Path) -> list[tuple[str, int, int | None, bool]]:
    """Die rows from the first opcode fetch at $0100: (kind, address, data, m1)."""
    rows = []
    with path.open() as stream:
        for row in csv.DictReader(stream):
            address = int(row["addr"], 16)
            kind = "read" if row["rd"] == "1" else "write" if row["wr"] == "1" else "internal"
            data = None if row["data"] == "--" else int(row["data"], 16)
            rows.append((kind, address, data, row["m1"] == "1"))
    start = next(i for i, r in enumerate(rows) if r[3] and r[1] == 0x0100)
    return rows[start:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", type=Path, default=ROOT / "tests" / "die_runs")
    parser.add_argument("--rerun", action="store_true", help="run the die model again")
    parser.add_argument("--show", type=int, default=25, help="mismatches to print")
    args = parser.parse_args()

    builder = build()
    rom = bytes(builder.image)
    args.work.mkdir(parents=True, exist_ok=True)
    rom_path, csv_path = args.work / "all_opcodes.gb", args.work / "die_bus.csv"
    rom_path.write_bytes(rom)
    (args.work / "all_opcodes.cases.json").write_text(json.dumps(builder.cases, indent=1))

    rows, tags, total = run_core(rom, builder.cases)
    if args.rerun or not csv_path.exists():
        print(f"running the die model for {total + 40} M-cycles ...")
        run_die(rom_path, csv_path, total + 8 + 40)
    die = read_die(csv_path)

    counts: Counter[str] = Counter()
    by_case: dict[str, list[str]] = defaultdict(list)
    for index, ours in enumerate(rows):
        if index >= len(die):
            counts["die ended early"] += 1
            break
        theirs = die[index]
        problem = None
        if ours[0] != theirs[0]:
            problem = f"kind {ours[0]} vs die {theirs[0]}"
        elif ours[1] != theirs[1]:
            problem = f"address {ours[1]:04X} vs die {theirs[1]:04X}"
        elif ours[0] != "internal" and theirs[2] is not None and ours[2] != theirs[2]:
            problem = f"data {ours[2]:02X} vs die {theirs[2]:02X}"
        counts["compared"] += 1
        if problem:
            counts[problem.split()[0]] += 1
            by_case[tags[index] or "(setup)"].append(f"cycle {index}: {problem}")
    print(f"{len(rows)} M-cycles on the core, {len(die)} on the die; {dict(counts)}")
    print(f"{len(by_case)} cases differ of {len(builder.cases)}")
    for shown, (name, problems) in enumerate(by_case.items()):
        if shown >= args.show:
            break
        print(
            f"  {name}: {problems[0]}"
            + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else "")
        )
    return 1 if by_case else 0


if __name__ == "__main__":
    sys.exit(main())
