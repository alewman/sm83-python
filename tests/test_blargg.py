"""Rung 2: blargg ``cpu_instrs`` 01 and 03-11 in the minimal harness.

Hardware-verified tier: blargg's CRCs come from his devcart runs on real consoles. The ROMs
print to the serial port; each must end with ``Passed``. 02-interrupts needs the timer
(``Timer doesn't work``) and belongs to the board (rung 6), so it is asserted to fail the
documented way rather than skipped silently.
"""

from pathlib import Path

import pytest

from sm83_python.harness import Harness

ROMS = Path(__file__).resolve().parents[1] / "reference" / "src" / "gb-test-roms" / "cpu_instrs"
INDIVIDUAL = sorted((ROMS / "individual").glob("*.gb"))
SLOW = {"09-op r,r", "10-bit ops", "11-op a,(hl)"}

pytestmark = pytest.mark.skipif(
    not INDIVIDUAL, reason="run scripts/fetch_references.py to fetch the test ROMs"
)


def run(path: Path):
    return Harness(path.read_bytes()).run(max_cycles=400_000_000)


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(p, marks=[pytest.mark.slow] if p.stem in SLOW else [], id=p.stem)
        for p in INDIVIDUAL
        if not p.stem.startswith("02-")
    ],
)
def test_cpu_instrs_passes(path):
    result = run(path)
    assert result.reason == "jump to self", result
    assert result.text.rstrip().endswith("Passed"), result.text


@pytest.mark.skipif(not (ROMS / "individual" / "02-interrupts.gb").is_file(), reason="no ROM")
def test_02_interrupts_fails_only_for_lack_of_a_timer():
    result = run(ROMS / "individual" / "02-interrupts.gb")
    assert "Timer doesn't work" in result.text and "Failed #4" in result.text
