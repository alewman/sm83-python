"""The generated opcode table agrees with its sources and with the decode rules."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from sm83_python._dispatch import HANDLER_NAMES
from sm83_python._opcodes import CB_OPCODES, OPCODES

ROOT = Path(__file__).resolve().parents[1]
TIMING = ROOT / "tests" / "gbctr_timing.json"
HOLES = {0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD}


def test_sizes_and_holes():
    assert len(OPCODES) == len(CB_OPCODES) == len(HANDLER_NAMES) == 256
    assert {c for c, o in enumerate(OPCODES) if o.category == "undefined"} == HOLES
    assert {c for c in range(256) if HANDLER_NAMES[c] == "_op_undefined"} == HOLES
    assert all(o.length == 2 for o in CB_OPCODES)


@pytest.mark.skipif(not TIMING.is_file(), reason="needs tests/gbctr_timing.json")
def test_categories_match_gbctr_timing_json():
    timing = json.loads(TIMING.read_text())
    for table, key in ((OPCODES, "opcodes"), (CB_OPCODES, "cb_opcodes")):
        for code, entry in enumerate(table):
            assert timing[key][f"0x{code:02X}"] == entry.category


@pytest.mark.skipif(not (ROOT / "reference" / "src" / "gb-ctr").is_dir(), reason="no references")
def test_generated_file_is_current():
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / "gen_opcode_table.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "run scripts/gen_opcode_table.py\n" + result.stdout + result.stderr
    )
