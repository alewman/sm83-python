#!/usr/bin/env python3
"""Run a ROM on Gekkio's VHDL SM83 and write its per-M-cycle bus rows as CSV.

    python scripts/die_run.py ROM.gb OUT.csv [--max-cycles N]

Uses the GHDL from reference/build/oss-cad-suite and the VUnit venv at reference/build/hdl-venv
(scripts/build_referees.py oss hdl). The simulation runs at about 6,400 instructions a second;
VUnit's scratch output goes to ``OUT.csv``'s directory under ``vunit_work/``. See
scripts/die/bus_dump_tb.vhd for the columns.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "reference" / "build"


def run_die(rom: Path, out: Path, max_cycles: int = 1_000_000, inject: Path | None = None) -> None:
    """Simulate ``rom`` on the die model, writing the bus CSV to ``out``."""
    python = BUILD / "hdl-venv" / "bin" / "python"
    if not python.exists() or not (BUILD / "oss-cad-suite" / "bin" / "ghdl").exists():
        raise SystemExit("run scripts/build_referees.py oss hdl first")
    out.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = f"{BUILD / 'oss-cad-suite' / 'bin'}:{env['PATH']}"
    env["VUNIT_SIMULATOR"] = "ghdl"
    work = out.parent / "vunit_work"
    subprocess.run(
        [
            str(python),
            str(ROOT / "scripts" / "die_sim.py"),
            str(rom),
            str(out),
            str(max_cycles),
            str(work),
            str(inject or ""),
        ],
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--max-cycles", type=int, default=1_000_000)
    parser.add_argument("--inject", type=Path, help="interrupt schedule: lines of 'cycle mask'")
    args = parser.parse_args()
    run_die(args.rom.resolve(), args.out.resolve(), args.max_cycles, args.inject)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
