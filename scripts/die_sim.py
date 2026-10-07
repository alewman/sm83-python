#!/usr/bin/env python3
"""Run a ROM on Gekkio's VHDL SM83 and write its per-M-cycle bus rows (validation.md rung 5).

Must run under the hdl venv's interpreter with GHDL on PATH; scripts/die_run.py does that:

    python scripts/die_run.py ROM.gb OUT.csv [--max-cycles N]

This file drives VUnit: it compiles the pinned die model together with
scripts/die/bus_dump_tb.vhd and test_soc_irq.vhd (this repository's testbench; the model stays untouched under
reference/) and runs it with the ROM and output path as generics.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HDL = ROOT / "reference" / "src" / "gb-research" / "sm83-cpu-core" / "hdl"
DIE = ROOT / "scripts" / "die"


def main() -> int:
    rom, out, max_cycles, work, inject = sys.argv[1:6]
    sys.path.insert(0, str(HDL))
    os.chdir(HDL)  # the model's source list is relative to its own directory
    from sm83_hdl.vunit import configure
    from vunit import VUnit

    ui = VUnit.from_argv(["--output-path", work, "--no-color"], compile_builtins=False)
    ui.add_vhdl_builtins()
    lib = configure(ui)
    lib.add_source_files([str(DIE / "test_soc_irq.vhd"), str(DIE / "bus_dump_tb.vhd")])
    bench = lib.test_bench("bus_dump_tb")
    bench.set_generic("rom_path", str(Path(rom).resolve()))
    bench.set_generic("out_path", str(Path(out).resolve()))
    bench.set_generic("max_cycles", int(max_cycles))
    if inject:
        bench.set_generic("inject_path", str(Path(inject).resolve()))
    ui.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
