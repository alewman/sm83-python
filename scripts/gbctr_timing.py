#!/usr/bin/env python3
"""Extract GBCTR's per-M-cycle instruction timing tables into JSON.

Gekkio's *Game Boy: Complete Technical Reference* keeps, for every instruction
category, a Typst dictionary of what happens on each machine cycle: the address
bus, the data bus, the IDU and ALU operations, and the memory access. This
script reads the pinned source (reference/src/gb-ctr) and writes
``tests/gbctr_timing.json`` (gitignored; regenerate, never edit):

    {"source": {"repo": ..., "rev": ...},
     "opcodes": {"0x00": "NOP", ...}, "cb_opcodes": {"0x00": "RLC_r", ...},
     "categories": {"NOP": {"mnemonic": "NOP", "paths": {"": [cycle, ...]}}, ...}}

A conditional category has two paths, ``"taken"`` and ``"not_taken"``;
everything else has the single path ``""``. Each cycle is one M-cycle after the
first fetch, in order, as ``{"kind", "addr", "data", "idu", "alu", "misc",
"mem_rw"}`` with GBCTR's text kept verbatim (``"U"`` = unspecified). The last
cycle of every path is the overlapped fetch of the next opcode (GBCTR's
"M(n+1)/M1").

``kind`` (``read``, ``write`` or ``internal``) is derived from the **data**
row (``X ← mem`` reads, ``mem ← X`` writes, anything else is internal), not
from GBCTR's ``mem_rw`` row, which is only a diagram label: it begins with the
*preceding* M1 ("opcode", "CB prefix"), so its entries sit one cycle early, and
in ``LD (nn),SP`` it names SPH before SPL where the data row and the pseudocode
write SPL first. ``mem_rw`` is kept, shifted by one so that it lines up, as
``mem_rw`` (the final fetch, which it leaves implicit, gets ``""``).

HALT, STOP and DAA have no timing in the source (TODO there), and the undefined
opcodes have none by nature; they are absent from ``categories``.

    python scripts/gbctr_timing.py           # writes tests/gbctr_timing.json
    python scripts/gbctr_timing.py --print   # one line per category instead
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GBCTR = ROOT / "reference" / "src" / "gb-ctr"
OUT = ROOT / "tests" / "gbctr_timing.json"
ROWS = {"addr": "addr", "data": "data", "idu_op": "idu", "alu_op": "alu", "misc_op": "misc"}


def split_top(body: str) -> list[str]:
    """Split a Typst tuple body on its top-level commas."""
    items, depth, current = [], 0, ""
    for char in body:
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        if char == "," and depth == 0:
            items.append(current)
            current = ""
        else:
            current += char
    if current.strip():
        items.append(current)
    return [clean(item) for item in items]


def clean(item: str) -> str:
    item = item.strip()
    if item.startswith("[") and item.endswith("]"):
        item = item[1:-1]
    item = re.sub(r'#hex\("([0-9A-Fa-f]+)"\)', r"$\1", item)
    item = re.sub(r"#sub\[(.*?)\]", r"\1", item)
    return item.replace("`", "").replace('"', "").strip()


def row(name: str, text: str) -> list[str] | None:
    match = re.search(rf"\b{name}: \((.*?)\),\s*\n", text, re.DOTALL)
    return split_top(match.group(1)) if match else None


def path(text: str) -> list[dict[str, str]]:
    duration = int(re.search(r"duration: (\d+)", text).group(1))
    rows = {key: row(name, text) for name, key in ROWS.items()}
    access = row("mem_rw", text) or []
    cycles = []
    for index in range(duration):
        cycle = {key: (values[index] if values and index < len(values) else "U")
                 for key, values in rows.items()}  # fmt: skip
        cycle = {"kind": kind(cycle["data"]), **cycle}
        cycle["mem_rw"] = access[index + 1] if index + 1 < len(access) else ""
        cycles.append(cycle)
    return cycles


def kind(data: str) -> str:
    if data.startswith("mem ←"):
        return "write"
    if data.endswith("← mem"):
        return "read"
    return "internal"


def extract() -> dict[str, object]:
    source = (GBCTR / "chapter" / "cpu" / "instruction-set.typ").read_text(encoding="utf-8")
    categories: dict[str, object] = {}
    for block in source.split("#instruction(")[1:]:
        label = re.search(r"<op:(\w+)>", block).group(1)
        mnemonic = re.search(r'mnemonic: "([^"]+)"', block).group(1)
        timing = block[block.index("timing: (") :]
        if "cc_true:" in timing:
            taken = timing[timing.index("cc_true:") :]
            not_taken = timing[timing.index("cc_false:") :]
            paths = {"taken": path(taken), "not_taken": path(not_taken)}
        else:
            paths = {"": path(timing)}
        categories[label] = {"mnemonic": mnemonic, "paths": paths}
    table = tomllib.loads((GBCTR / "opcodes.toml").read_text(encoding="utf-8"))
    rev = subprocess.run(
        ["git", "-C", str(GBCTR), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    return {
        "source": {"repo": "https://github.com/Gekkio/gb-ctr", "rev": rev},
        "opcodes": {f"0x{i:02X}": op["category"] for i, op in enumerate(table["opcodes"])},
        "cb_opcodes": {f"0x{i:02X}": op["category"] for i, op in enumerate(table["cb_opcodes"])},
        "categories": categories,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--print", action="store_true", help="summarise instead of writing")
    args = parser.parse_args()
    data = extract()
    if args.print:
        for label, entry in data["categories"].items():
            for name, cycles in entry["paths"].items():
                shown = " | ".join(f"{c['kind'][0].upper()}@{c['addr']}" for c in cycles)
                print(f"{label:12} {name:9} {len(cycles)}  {shown}")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    missing = sorted(set(data["opcodes"].values()) | set(data["cb_opcodes"].values()))
    missing = [m for m in missing if m not in data["categories"]]
    print(f"wrote {OUT}: {len(data['categories'])} categories; no timing for {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
