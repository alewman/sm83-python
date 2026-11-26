"""Rung 5: the core against Gekkio's die-traced VHDL SM83, end to end.

Slow: each runs a simulator. They skip when the simulator is not built (``python
scripts/build_referees.py oss hdl``). What they run and what they claim is in
docs/validation.md rung 5: Gekkio's VHDL SM83 on its mock SoC, every opcode, both paths, CB,
interrupt dispatch and the entry to HALT, compared bus cycle by bus cycle (kind, address,
data), internal cycles included.

Until 2026-11-26 two more tests ran the same ROM, and HALT woken by the timer, on msinger's
dmg-sim; dmg-sim is set aside for the author's wishes (docs/provenance.md "Author respect").
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
