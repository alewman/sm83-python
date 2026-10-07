#!/usr/bin/env python3
"""HALT, woken for real: the core against msinger's dmg-sim netlist (validation.md rung 5).

The VHDL model's mock SoC cannot wake a halted CPU; dmg-sim is the whole DMG-CPU B, so it can.
Each case starts the timer (TIMA = $FC overflows four ticks later, 4 M-cycles each at 262144 Hz) and
then HALTs after 0..11 padding NOPs, with IME off or on, which sweeps the interrupt across the
HALT: already pending, arriving as the HALT fetches, or waking a halted CPU.

The simulator's own IF register says when the interrupt was raised; the core is given its
request at that M-cycle (relative to the instruction that started the timer, the last fetch
before the HALT that all of them share) and the two bus sequences are compared case by case.
``--skew`` shifts the core's request to find how its callback moment maps to the netlist's IF.

    python scripts/dmgsim_halt.py [--work DIR] [--rerun] [--skew N] [--detail CASE]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from die_compare import MockSoc, compare_rows, side_by_side, starts  # noqa: E402
from die_programs import Builder, add_timer_halt_cases  # noqa: E402
from dmgsim_rows import read_rows  # noqa: E402
from dmgsim_run import run_dmgsim  # noqa: E402

from sm83_python import CPUState  # noqa: E402


def build_rom() -> Builder:
    b = Builder()
    add_timer_halt_cases(b)
    b.case("end", [0x18, 0xFE])
    return b


def measure(rows: list, cases: list[dict]) -> dict[str, tuple[int, int, int]]:
    """Per timer case: (row of the timer start's fetch, row IF rose, row of the HALT's fetch)."""
    found = {}
    for case in cases:
        if not case.get("timer_halt"):
            continue
        tac = case["address"] + case["tac_offset"]
        halt = case["address"] + case["halt_offset"]
        i_tac = next((i for i, r in enumerate(rows) if r[3] and r[0] == "read" and r[1] == tac), -1)
        i_halt = next(
            (i for i, r in enumerate(rows) if r[3] and r[0] == "read" and r[1] == halt), -1
        )
        i_if = next(
            (
                i
                for i in range(max(i_tac, 1), len(rows))
                if rows[i][5] & 4 and not rows[i - 1][5] & 4
            ),
            -1,
        )
        found[case["name"]] = (i_tac, i_if, i_halt)
    return found


def run_core(rom: bytes, cases: list[dict], measured: dict, skew: int) -> list:
    triggers = {}
    for case in cases:
        if case["name"] in measured:
            i_tac, i_if, _ = measured[case["name"]]
            triggers[case["address"] + case["tac_offset"]] = (i_if - i_tac + skew, 0x04)
    soc = MockSoc(rom, triggers)
    soc.cpu.restore_state(CPUState(pc=0x0100))
    end = cases[-1]["address"]
    loops = 0
    while loops < 2 and len(soc.rows) < 60_000:
        if soc.cpu.pc == end:
            loops += 1
        soc.cpu.step()
    return soc.rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", type=Path, default=ROOT / "tests" / "die_runs")
    parser.add_argument("--rerun", action="store_true", help="run dmg-sim again")
    parser.add_argument("--skew", type=int, default=0)
    parser.add_argument("--detail", help="print a case (name prefix) side by side")
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)

    b = build_rom()
    rom_path, log = args.work / "timer_halt.gb", args.work / "timer_halt.log"
    rom_path.write_bytes(bytes(b.image))
    if args.rerun or not log.exists():
        print("running dmg-sim ...")
        run_dmgsim(rom_path, log, millis=6)
    sim = read_rows(log)
    measured = measure(sim, b.cases)
    core = run_core(bytes(b.image), b.cases, measured, args.skew)

    at_core = starts(core, b.cases, lambda r: r[0] == "read" and r[3] == 1)
    at_sim = starts(sim, b.cases, lambda r: r[3] and r[0] == "read")
    bad = 0
    for i, case in enumerate(b.cases):
        if at_core[i] < 0 or at_sim[i] < 0:
            print(f"  {case['name']}: first fetch missing")
            bad += 1
            continue
        last = i + 1 == len(b.cases)
        mine = core[at_core[i] : (len(core) if last else at_core[i + 1])]
        theirs = sim[at_sim[i] : (len(sim) if last else at_sim[i + 1])]
        problem = None
        if len(mine) != len(theirs) and not last:
            problem = f"{len(mine)} M-cycles vs sim {len(theirs)}"
        for j in range(min(len(mine), len(theirs))):
            found = compare_rows(mine[j], theirs[j])
            if found and problem is None:
                problem = f"cycle {j}: {found}"
        info = ""
        if case["name"] in measured:
            _, i_if, i_halt = measured[case["name"]]
            info = f" [IF rose {i_if - i_halt:+d} from the HALT fetch, {sum(1 for r in theirs if not r[4])} halted]"
        print(f"  {case['name']}: {problem or 'same'}{info}")
        bad += bool(problem)
        if args.detail and case["name"].startswith(args.detail):
            print("\n".join(side_by_side(mine, theirs)))
    print(f"{len(b.cases)} cases, {bad} differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
