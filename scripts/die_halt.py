#!/usr/bin/env python3
"""HALT entry against the die model: one small simulation per scenario (validation.md rung 5).

The mock SoC cannot wake a halted die (the interrupt latch that does it is clocked by a gated
clock), so every scenario ends in a halted die. Up to that point the core and the die must make
the same M-cycles: HALT's own cycle (a fetch of the next byte without moving PC), the moment the
CPU decides to halt rather than not (the HALT bug, a dispatch from the HALT), and what follows.
The first row where the die is halted and the core is not is the core's wake-up, which the die
cannot show; it is reported, not compared.

An interrupt raised ``k`` M-cycles from the HALT's fetch is raised in both: by the core's
callback for that cycle, and in the die for one M-cycle starting after that cycle's row. If the
two disagree about whether the HALT sees it, the offset between the two moments is the lesson.

    python scripts/die_halt.py [--work DIR] [--skew N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from die_compare import MockSoc, compare_rows, read_die, triggers_of  # noqa: E402
from die_programs import add_halt_case, add_pending_halt_cases, build_single  # noqa: E402
from die_run import run_die  # noqa: E402

from sm83_python import CPUState  # noqa: E402


def core_rows(rom: bytes, cases: list[dict], skew: int) -> list:
    """Run the scenario until the closing ``JR $`` has run twice."""
    soc = MockSoc(rom, triggers_of(cases, skew))
    soc.cpu.restore_state(CPUState(pc=0x0100))
    end = cases[-1]["address"]
    loops = 0
    while loops < 2 and len(soc.rows) < 400:
        if soc.cpu.pc == end:
            loops += 1
        soc.cpu.step()
    return soc.rows


def run_scenario(name: str, add, work: Path, skew: int) -> str:
    b = build_single(add)
    rom = bytes(b.image)
    rom_path, csv_path, inject = work / "halt.gb", work / "halt.csv", work / "halt_inject.txt"
    rom_path.write_bytes(rom)
    inject.write_text("".join(f"{a:04X} {k} {m}\n" for a, (k, m) in triggers_of(b.cases).items()))
    core = core_rows(rom, b.cases, skew)
    run_die(rom_path, csv_path, len(core) + 30, inject)
    die = read_die(csv_path)
    # both start at the first fetch of the case; skip the entry stub's rows
    start = b.cases[0]["start"]
    c0 = next(i for i, r in enumerate(core) if r[0] == "read" and r[3] == 1 and r[1] == start)
    d0 = next(i for i, r in enumerate(die) if r[3] and r[0] == "read" and r[1] == start)
    halted = 0
    for j in range(min(len(core) - c0, len(die) - d0)):
        mine, theirs = core[c0 + j], die[d0 + j]
        if not theirs[4]:
            halted += 1
            if mine[0] != "internal":
                return f"{name}: die halted for good; core woke after {halted} halted rows (ok)"
            continue
        found = compare_rows(mine, theirs)
        if found:
            return f"{name}: DIFFERS at case row {j}: {found}"
    return f"{name}: same {min(len(core) - c0, len(die) - d0)} rows ({halted} halted)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", type=Path, default=ROOT / "tests" / "die_runs")
    parser.add_argument("--skew", type=int, default=0, help="shift the core's requests")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    scenarios = []
    for ime in (False, True):
        for after in range(-1, 6):
            label = f"HALT ime={int(ime)} IF {after:+d}"
            scenarios.append((label, lambda b, i=ime, a=after: add_halt_case(b, i, a)))
    scenarios.append(("HALT pending at entry", add_pending_halt_cases))
    status = 0
    for label, add in scenarios:
        line = run_scenario(label, add, args.work, args.skew)
        print(line)
        status |= "DIFFERS" in line
    return status


if __name__ == "__main__":
    sys.exit(main())
