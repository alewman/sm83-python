"""Rung 0: the core's bus schedule equals GBCTR's, for every opcode and both paths.

``tests/gbctr_timing.json`` (generated from the pinned GBCTR source by
scripts/gbctr_timing.py) lists, per instruction category, one entry per M-cycle after the
first fetch: the address bus, the IDU operation and the data movement. This test evaluates
those symbolic entries on a random state, as GBCTR defines them, and requires the core to
make the same (kind, address, IDU direction) sequence. The final entry of every path is the
next instruction's fetch, which belongs to the next ``step()`` in this core, so it is dropped
and the step's own opcode fetch is put in front.

Tier: research documentation (GBCTR), die-informed. It is the bus judge until rung 5 asks the
die model. HALT, STOP, DAA's timing and the undefined opcodes are not in GBCTR's tables and
are covered by tests/test_special_states.py.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from sm83_python import SM83, CPUState
from sm83_python._opcodes import CB_OPCODES, OPCODES

TIMING = Path(__file__).resolve().parents[1] / "tests" / "gbctr_timing.json"
pytestmark = pytest.mark.skipif(
    not TIMING.is_file(), reason="run scripts/gbctr_timing.py to generate tests/gbctr_timing.json"
)

NOT_IN_GBCTR = {"HALT", "STOP", "undefined", "CB"}
PAIRS = ("bc", "de", "hl", "sp")


class Recorder:
    """A RAM host that logs (kind, address, IDU direction, data) for every callback."""

    def __init__(self, memory: bytearray) -> None:
        self.memory = memory
        self.log: list[tuple[str, int, int, int]] = []
        self.cpu = SM83(self.read, self.write, self.idle)

    def read(self, address: int) -> int:
        self.log.append(("read", address, self.cpu.idu, self.memory[address]))
        return self.memory[address]

    def write(self, address: int, value: int) -> None:
        self.log.append(("write", address, self.cpu.idu, value))
        self.memory[address] = value

    def idle(self, address: int) -> None:
        self.log.append(("internal", address, self.cpu.idu, 0))


def load_timing() -> dict:
    return json.loads(TIMING.read_text())


def cases() -> list[tuple[int, bool, str, str]]:
    """(opcode, prefixed, category, path) for every opcode GBCTR describes."""
    timing = load_timing()
    out = []
    for prefixed, table in ((False, OPCODES), (True, CB_OPCODES)):
        for code, entry in enumerate(table):
            if entry.category in NOT_IN_GBCTR:
                continue
            out.extend(
                (code, prefixed, entry.category, path)
                for path in timing["categories"][entry.category]["paths"]
            )
    return out


CASES = cases() if TIMING.is_file() else []


def signed(byte: int) -> int:
    return byte - 0x100 if byte & 0x80 else byte


def force_condition(flags: int, code: int, taken: bool) -> int:
    """Set F so that condition ``code`` (NZ, Z, NC, C) evaluates to ``taken``."""
    bit = 0x80 if code < 2 else 0x10
    wanted_set = (code & 1 == 1) == taken
    return (flags | bit) if wanted_set else (flags & ~bit)


def expected_schedule(cycles: list[dict], op: int, state: dict, observed: list[int]) -> list:
    """Evaluate GBCTR's symbolic cycles on a register state.

    ``observed`` holds the byte each read cycle returned, which feeds Z and W exactly as the
    data-bus rows say (``Z <- mem``, ``W <- mem``).
    """
    regs = dict(state)
    z = w = 0
    out = []
    for index, cycle in enumerate(cycles):
        wz = w << 8 | z
        address = {
            "PC": regs["pc"],
            "HL": regs["hl"],
            "BC": regs["bc"],
            "DE": regs["de"],
            "SP": regs["sp"],
            "WZ": wz,
            "$FF00+C": 0xFF00 | regs["c"],
            "$FF00+Z": 0xFF00 | z,
            "$0000": 0,
            # GBCTR words JR's internal address "PCH"; the bus carries PC (rung 5 settles it)
            "PCH": regs["pc"],
            "rr": regs[PAIRS[op >> 4 & 3]],
        }[cycle["addr"]]
        idu = cycle["idu"]
        step = 1 if idu.endswith("+ 1") else -1 if idu.endswith("- 1") else 0
        out.append((cycle["kind"], address, step))
        match idu.split(" ← ")[0]:
            case "PC":
                regs["pc"] = (regs["pc"] + 1) & 0xFFFF
            case "HL" | "SP" as name:
                regs[name.lower()] = (regs[name.lower()] + step) & 0xFFFF
            case "WZ":
                wz = (wz + 1) & 0xFFFF
                w, z = wz >> 8, wz & 0xFF
            case "rr":
                name = PAIRS[op >> 4 & 3]
                regs[name] = (regs[name] + step) & 0xFFFF
        if idu == "SP ← HL":
            regs["sp"] = regs["hl"]
        if cycle["data"] == "Z ← mem":
            z = observed[index]
        elif cycle["data"] == "W ← mem":
            w = observed[index]
        if cycle["misc"].startswith("PC ← WZ"):
            regs["pc"] = w << 8 | z
        elif cycle["misc"] == "PC ← addr":
            regs["pc"] = op & 0x38
    return out


@pytest.mark.parametrize(
    ("code", "prefixed", "category", "path"),
    CASES,
    ids=[f"{'cb ' if p else ''}{c:02x}-{cat}-{path or 'only'}" for c, p, cat, path in CASES],
)
def test_bus_schedule_matches_gbctr(code, prefixed, category, path):
    cycles = load_timing()["categories"][category]["paths"][path]
    rng = random.Random(code * 1000 + prefixed)
    for _ in range(8):
        memory = bytearray(rng.randbytes(0x10000))
        memory[0xFFFF] = 0  # the core owns $FFFF and reads it as IE
        pc = rng.randrange(0x0200, 0xE000)
        if prefixed:
            memory[pc], memory[pc + 1] = 0xCB, code
        else:
            memory[pc] = code
        regs = {
            "a": rng.randrange(256),
            "b": rng.randrange(256),
            "c": rng.randrange(256),
            "d": rng.randrange(256),
            "e": rng.randrange(256),
            "h": rng.randrange(0x02, 0xE0),
            "l": rng.randrange(256),
            "sp": rng.randrange(0x0200, 0xE000),
            "pc": pc,
        }
        flags = rng.randrange(16) << 4
        if path:  # conditional: put the flags on the requested side of the condition
            flags = force_condition(flags, code >> 3 & 3, path == "taken")
        recorder = Recorder(memory)
        cpu = recorder.cpu
        log = recorder.log
        cpu.restore_state(CPUState(f=flags, **regs))
        before = {
            "pc": pc + 1,  # the fetch has put PC past the opcode
            "sp": regs["sp"],
            "hl": regs["h"] << 8 | regs["l"],
            "bc": regs["b"] << 8 | regs["c"],
            "de": regs["d"] << 8 | regs["e"],
            "c": regs["c"],
        }
        consumed = cpu.step()
        assert consumed == len(log), "step() must return the number of callbacks made"
        # the step's opcode fetch, then GBCTR's cycles without the trailing next-instruction fetch
        wanted = [
            ("read", pc, 1),
            *expected_schedule(cycles[:-1], code, before, [d for *_, d in log[1:]]),
        ]
        got = [(kind, address, idu) for kind, address, idu, _ in log]
        assert got == wanted, f"flags {flags:#04x}"
