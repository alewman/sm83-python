"""Rung 5: the core against two independent die-traced models, end to end.

Slow: each runs a simulator. They skip when the simulators are not built (``python
scripts/build_referees.py oss hdl dmgsim``). What they run and what they claim is in
docs/validation.md rung 5:

* Gekkio's VHDL SM83 on its mock SoC: every opcode, both paths, CB, interrupt dispatch and the
  entry to HALT, compared bus cycle by bus cycle (kind, address, data), internal cycles included;
* msinger's dmg-sim, a netlist of the whole DMG-CPU B: the same ROM, and HALT woken by the timer.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "reference" / "build"
HAVE_VHDL = (BUILD / "hdl-venv" / "bin" / "python").exists() and (
    BUILD / "oss-cad-suite" / "bin" / "ghdl"
).exists()
HAVE_DMGSIM = (BUILD / "oss-cad-suite" / "bin" / "iverilog").exists() and (
    ROOT / "reference" / "src" / "dmg-sim"
).is_dir()


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", *args], capture_output=True, text=True, check=False, cwd=ROOT
    )


pytestmark = pytest.mark.slow


@pytest.mark.skipif(not HAVE_VHDL, reason="needs GHDL and the hdl venv (build_referees.py oss hdl)")
def test_vhdl_model_all_opcodes_agree(tmp_path):
    result = run_script("scripts/die_compare.py", "--rerun", "--work", str(tmp_path))
    assert result.returncode == 0, result.stdout[-2000:]
    assert "0 cases differ" in result.stdout


@pytest.mark.skipif(not HAVE_VHDL, reason="needs GHDL and the hdl venv (build_referees.py oss hdl)")
def test_vhdl_model_halt_entry_agrees(tmp_path):
    result = run_script("scripts/die_halt.py", "--work", str(tmp_path))
    assert result.returncode == 0, result.stdout[-2000:]
    assert "DIFFERS" not in result.stdout and result.stdout.count("same") >= 3


@pytest.mark.skipif(not HAVE_DMGSIM, reason="needs Icarus Verilog and dmg-sim (build_referees.py)")
def test_dmgsim_all_opcodes_agree(tmp_path):
    rom = tmp_path / "all.gb"
    log = tmp_path / "all.log"
    first = run_script("scripts/die_compare.py", "--work", str(tmp_path), "--dmgsim", str(log))
    del first  # builds all_opcodes.gb in the work directory; the simulation needs it first
    sim = run_script("scripts/dmgsim_run.py", str(tmp_path / "all_opcodes.gb"), str(log))
    assert sim.returncode == 0, sim.stderr[-2000:]
    result = run_script("scripts/die_compare.py", "--work", str(tmp_path), "--dmgsim", str(log))
    assert result.returncode == 0, result.stdout[-2000:]
    assert "0 cases differ" in result.stdout
    del rom


@pytest.mark.skipif(not HAVE_DMGSIM, reason="needs Icarus Verilog and dmg-sim (build_referees.py)")
def test_dmgsim_halt_woken_by_the_timer_agrees(tmp_path):
    result = run_script("scripts/dmgsim_halt.py", "--rerun", "--work", str(tmp_path))
    assert result.returncode == 0, result.stdout[-2000:]
    assert "49 cases, 0 differ" in result.stdout
