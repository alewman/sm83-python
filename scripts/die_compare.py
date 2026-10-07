#!/usr/bin/env python3
"""Compare the core's bus with Gekkio's VHDL SM83, cycle for cycle (validation.md rung 5).

Builds the all-opcodes ROM (scripts/die_programs.py), runs it on the core behind a model of
the die testbench's mock SoC, runs it on the die model (scripts/die_run.py), and compares the
two M-cycle sequences case by case (``--dmgsim LOG`` swaps the VHDL model for msinger's
independent netlist simulation, scripts/dmgsim_run.py): kind (read, write or internal) and address always, data
for reads and writes. The comparison resynchronises at the start of every case, so one
disagreement does not hide the rest. The die is die-traced, so where it and the core disagree
the die decides, unless it also disagrees with a hardware-verified test.

HALT cases need an interrupt raised at a chosen moment, which the mock SoC cannot do: both
sides get the same request ``k`` M-cycles after the fetch of a named instruction. While the
die's CPU clock is gated (it is, while halted) its rows are labelled and the core must make an
internal cycle at $0000, as the die does.

    python scripts/die_compare.py [--work DIR] [--rerun] [--show N] [--detail CASE]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from die_programs import build  # noqa: E402
from die_run import run_die  # noqa: E402
from dmgsim_rows import read_rows as read_dmgsim  # noqa: E402

from sm83_python import SM83, CPUState  # noqa: E402

Row = tuple[str, int, int | None, int]  # kind, address, data, idu


class MockSoc:
    """The die testbench's memory map: ROM, WRAM, HRAM, IF, LY and SC; the rest floats high."""

    def __init__(self, rom: bytes, triggers: dict[int, tuple[int, int]] | None = None) -> None:
        self.rom = rom
        self.memory = bytearray(0x10000)
        self.rows: list[Row] = []
        self.written: set[int] = set()  # WRAM the program has written: the rest is power-on junk
        self.triggers = triggers or {}  # fetch address -> (cycles later, IF mask) to raise IF
        self.due: list[tuple[int, int]] = []  # (row index, IF mask) still to raise
        self.cpu = SM83(self.read, self.write, self.idle)

    def _row(self, kind: str, address: int, value: int | None) -> None:
        """Log one M-cycle and raise any interrupt scheduled for it."""
        index = len(self.rows)
        self.rows.append((kind, address, value, self.cpu.idu))
        for due in [d for d in self.due if d[0] == index]:
            self.due.remove(due)
            for bit in range(5):
                if due[1] >> bit & 1:
                    self.cpu.request_interrupt(bit)

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
        if self.cpu.idu == 1 and address in self.triggers:  # a fetch that starts a countdown
            after, mask = self.triggers[address]
            self.due.append((len(self.rows) + after, mask))
        unwritten = 0xC000 <= address < 0xE000 and address not in self.written
        self._row(
            "read", address, None if unwritten else value
        )  # junk on a real chip: not compared
        return value

    def write(self, address: int, value: int) -> None:
        if address == 0xFF0F:
            self.cpu.if_ = value & 0x1F
        elif 0xC000 <= address < 0xE000 or address >= 0xFF80:
            self.memory[address] = value
            self.written.add(address)
        self._row("write", address, value)

    def idle(self, address: int) -> None:
        self._row("internal", address, None)


def triggers_of(cases: list[dict], skew: int = 0) -> dict[int, tuple[int, int]]:
    """Interrupt requests the cases ask for: fetch address -> (M-cycles later, IF mask)."""
    return {
        c["address"] + c["trigger_offset"]: (c["inject_after"] + skew, c["mask"])
        for c in cases
        if "trigger_offset" in c
    }


def run_core(rom: bytes, cases: list[dict], skew: int = 0) -> list[Row]:
    """The core's rows from the first fetch at $0100 until it locks, then 40 locked cycles."""
    soc = MockSoc(rom, triggers_of(cases, skew))
    soc.cpu.restore_state(CPUState(pc=0x0100))
    while not soc.cpu.locked:
        soc.cpu.step()
        if len(soc.rows) > 200_000:
            raise RuntimeError("the core did not reach the final lock")
    for _ in range(40):
        soc.cpu.step()
    return soc.rows


def read_die(path: Path) -> list[tuple[str, int, int | None, bool, bool]]:
    """Die rows from the first opcode fetch at $0100: (kind, address, data, m1, running).
    ``running`` is the CPU clock enable; the die gates it while halted."""
    rows = []
    with path.open() as stream:
        for row in csv.DictReader(stream):
            kind = "read" if row["rd"] == "1" else "write" if row["wr"] == "1" else "internal"
            data = None if row["data"] == "--" else int(row["data"], 16)
            rows.append((kind, int(row["addr"], 16), data, row["m1"] == "1", row["run"] == "1"))
    start = next(i for i, r in enumerate(rows) if r[3] and r[1] == 0x0100)
    return rows[start:]


def starts(rows: list, cases: list[dict], is_fetch) -> list[int]:
    """Row index where each case's first instruction is fetched, in order (or -1)."""
    found, want = [], 0
    for index, row in enumerate(rows):
        if want < len(cases) and is_fetch(row) and row[1] == cases[want]["start"]:
            found.append(index)
            want += 1
    return found + [-1] * (len(cases) - len(found))


def compare_rows(ours: Row, theirs) -> str | None:
    """How a core row differs from a die row, or None."""
    if not theirs[4]:  # the die's CPU clock is stopped: halted, driving $0000 and nothing else
        if ours[0] != "internal":
            return f"die halted, core made a {ours[0]} cycle"
        return None if ours[1] == 0 else f"halted address {ours[1]:04X}, die $0000"
    if ours[0] != theirs[0]:
        return f"kind {ours[0]} vs die {theirs[0]}"
    if ours[1] != theirs[1]:
        return f"address {ours[1]:04X} vs die {theirs[1]:04X}"
    if None not in (ours[2], theirs[2]) and ours[2] != theirs[2]:
        return f"data {ours[2]:02X} vs die {theirs[2]:02X}"
    return None


def side_by_side(ours: list[Row], theirs: list) -> list[str]:
    lines = []
    for i in range(max(len(ours), len(theirs))):
        o = ours[i] if i < len(ours) else None
        d = theirs[i] if i < len(theirs) else None
        left = (
            ""
            if o is None
            else f"{o[0][:5]:<5} {o[1]:04X} {'--' if o[2] is None else f'{o[2]:02X}'} idu{o[3]:+d}"
        )
        right = (
            ""
            if d is None
            else (
                f"{d[0][:5]:<5} {d[1]:04X} {'--' if d[2] is None else f'{d[2]:02X}'} "
                f"{'m1' if d[3] else '  '} {'run' if d[4] else 'HALT'}"
            )
        )
        lines.append(f"  {i:3} core {left:<24} | die {right}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work", type=Path, default=ROOT / "tests" / "die_runs")
    parser.add_argument("--rerun", action="store_true", help="run the die model again")
    parser.add_argument("--show", type=int, default=25, help="cases to list")
    parser.add_argument("--detail", help="print a case (name prefix) side by side")
    parser.add_argument("--skew", type=int, default=0, help="shift the core's interrupt requests")
    parser.add_argument(
        "--dmgsim", type=Path, help="compare with a dmg-sim probe log (scripts/dmgsim_run.py)"
    )
    args = parser.parse_args()

    builder = build()
    cases = builder.cases
    rom = bytes(builder.image)
    args.work.mkdir(parents=True, exist_ok=True)
    rom_path, csv_path = args.work / "all_opcodes.gb", args.work / "die_bus.csv"
    inject_path = args.work / "inject.txt"
    rom_path.write_bytes(rom)
    (args.work / "all_opcodes.cases.json").write_text(json.dumps(cases, indent=1))

    core = run_core(rom, cases, args.skew)
    inject_path.write_text(
        "".join(
            f"{address:04X} {after} {mask}\n"
            for address, (after, mask) in triggers_of(cases).items()
        )
    )
    if args.dmgsim:
        die = read_dmgsim(args.dmgsim)  # same row shape as the VHDL model's
    else:
        if args.rerun or not csv_path.exists():
            print(f"running the die model for {len(core) + 60} M-cycles ...")
            run_die(rom_path, csv_path, len(core) + 60, inject_path)
        die = read_die(csv_path)

    at_core = starts(core, cases, lambda r: r[0] == "read" and r[3] == 1)
    at_die = starts(die, cases, lambda r: r[3] and r[0] == "read")
    differing: list[tuple[dict, str]] = []
    compared = 0
    for i, case in enumerate(cases):
        if at_core[i] < 0 or at_die[i] < 0:
            differing.append((case, "the case's first fetch is missing on one side"))
            continue
        last = i + 1 == len(cases)
        end_core = len(core) if last else at_core[i + 1]
        end_die = len(die) if last else at_die[i + 1]
        mine, theirs = core[at_core[i] : end_core], die[at_die[i] : end_die]
        problem = None
        if len(mine) != len(theirs) and not last:
            problem = f"{len(mine)} M-cycles vs die {len(theirs)}"
        for j in range(min(len(mine), len(theirs))):
            compared += 1
            found = compare_rows(mine[j], theirs[j])
            if found and problem is None:
                problem = f"cycle {j}: {found}"
        if problem:
            differing.append((case, problem))
        if args.detail and case["name"].startswith(args.detail):
            print(f"{case['name']}:")
            print("\n".join(side_by_side(mine, theirs)))
    halted = sum(1 for r in die if not r[4])
    print(
        f"{len(core)} M-cycles on the core, {len(die)} on the die ({halted} halted); "
        f"{compared} compared in {len(cases)} cases; {len(differing)} cases differ"
    )
    for case, problem in differing[: args.show]:
        print(f"  {case['name']}: {problem}")
    return 1 if differing else 0


if __name__ == "__main__":
    sys.exit(main())
