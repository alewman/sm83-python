#!/usr/bin/env python3
"""Run a ROM on msinger's dmg-sim and record the external bus (validation.md rung 5).

dmg-sim is a netlist-level (SystemVerilog, Icarus) simulation of the whole DMG-CPU B, traced
independently of Gekkio's VHDL model, so agreement between the two and the core is evidence from
two separate die tracings. This builds a copy of its simulator with scripts/dmgsim/bus_probe.sv
added (the pinned sources under reference/ stay untouched), gives it a tiny boot
ROM that disables itself and falls into the cartridge at $0100, and writes the probe's raw lines.

    python scripts/dmgsim_run.py ROM.gb OUT.log [--millis 12]

Simulation costs minutes of wall time per millisecond of simulated time.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "reference" / "build"
SIM = ROOT / "reference" / "src" / "dmg-sim"
PROBE = ROOT / "scripts" / "dmgsim" / "bus_probe.sv"
#: JP $00FC at the start; at $00FC: LD A,1 ; LDH ($FF50),A, the last instruction, so that the next
#: fetch is the cartridge's $0100 (as in the real boot ROM, which ends the same way).
BOOT = bytes([0xC3, 0xFC, 0x00]) + bytes(0xFC - 3) + bytes([0x3E, 0x01, 0xE0, 0x50])


def environment() -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{BUILD / 'oss-cad-suite' / 'bin'}:{env['PATH']}"
    return env


def build_probe_vvp(work: Path) -> Path:
    """Compile dmg-sim with the probe, reusing the Makefile's own file lists."""
    work.mkdir(parents=True, exist_ok=True)
    out = work / "dmg_probe.vvp"
    if out.exists() and out.stat().st_mtime > PROBE.stat().st_mtime:
        return out
    dry = subprocess.run(
        ["make", "-n", "-B", "dmg_cpu_b_gameboy.vvp"],
        cwd=SIM, env=environment(), capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    command = re.sub(r"\\\n", " ", dry).split()
    command[command.index("-o") + 1] = str(out)
    subprocess.run([*command, str(PROBE)], cwd=SIM, env=environment(), check=True)
    return out


def run_dmgsim(rom: Path, log: Path, millis: float = 12.0) -> None:
    work = log.parent
    work.mkdir(parents=True, exist_ok=True)
    vvp = build_probe_vvp(work)
    boot = work / "tiny_boot.bin"
    boot.write_bytes(BOOT)
    with log.open("w") as stream:
        subprocess.run(
            ["vvp", "-N", str(vvp), "-none", f"+BOOTROM={boot}", f"+ROM={rom}",
             f"+SECS={millis / 1000:.6f}", "+MBC_TYPE=00", "+RAM_SIZE=00"],
            cwd=work, env=environment(), stdout=stream, check=True,
        )  # fmt: skip


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("rom", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--millis", type=float, default=12.0, help="simulated milliseconds")
    args = parser.parse_args()
    run_dmgsim(args.rom.resolve(), args.out.resolve(), args.millis)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
