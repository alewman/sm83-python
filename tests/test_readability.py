"""Readability contract for the instruction core, enforced the way correctness is.

The core is a reference, so every opcode handler must be findable by the mnemonic an SM83
programmer would grep for, must live in the module that owns that instruction group, and must
say where its rule comes from. Derived from the source with :mod:`ast` (nothing is executed):

1. Every ``_op_*`` and ``_cb_*`` method has a docstring whose headline (first paragraph) lists
   the mnemonics it implements, optionally followed by ``-- explanation``, and ends with the
   source of its rule in parentheses (GBCTR category, Pan Docs, docs item such as ``U4``).
2. Every handler lives in the module that owns its mnemonic group.
3. Every mnemonic of the generated opcode table is claimed by the handler that decodes it, and
   no handler name is defined twice across the mixins (the MRO would silently shadow one).
4. The decode table names only handlers that exist, and every ``_op_*`` is reachable from it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from sm83_python._dispatch import HANDLER_NAMES
from sm83_python._opcodes import CB_OPCODES, OPCODES

SRC = Path(__file__).resolve().parents[1] / "src" / "sm83_python"

OWNERS: dict[str, frozenset[str]] = {
    module: frozenset(mnemonics.split())
    for module, mnemonics in {
        "_loads.py": "LD LDH PUSH POP",
        "_alu.py": "ADD ADC SUB SBC AND XOR OR CP INC DEC DAA CPL SCF CCF",
        "_rotate.py": "RLC RRC RL RR SLA SRA SWAP SRL RLCA RRCA RLA RRA BIT RES SET CB",
        "_control.py": "JP JR CALL RET RETI RST DI EI NOP HALT STOP ILLEGAL",
    }.items()
}
#: Mnemonic words the table uses that are spelled differently in a docstring headline.
ALIASES = {"DB": "ILLEGAL"}

_SEGMENT = re.compile(r"^(?P<word>[A-Z]+)(?:\s.*)?$")
_CITATION = re.compile(r"\((?=[^)]*(?:GBCTR|Pan Docs|timing\.md|U\d+))[^)]*\)\.?$")


def handlers() -> dict[str, tuple[str, str]]:
    """name -> (module file, docstring) for every ``_op_*`` / ``_cb_*`` method."""
    found: dict[str, tuple[str, str]] = {}
    for path in sorted(SRC.glob("_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and node.name.startswith(("_op_", "_cb_")):
                assert node.name not in found, f"{node.name} defined twice ({path.name})"
                found[node.name] = (path.name, ast.get_docstring(node) or "")
    return found


HANDLERS = handlers()


def headline(doc: str) -> str:
    return doc.split("\n\n")[0].replace("\n", " ").strip()


def mnemonics(doc: str) -> list[str]:
    """The mnemonic words a docstring headline claims."""
    text = headline(doc).split(" -- ")[0]
    words = []
    for segment in text.split("/"):
        match = _SEGMENT.match(segment.strip())
        assert match, f"headline segment {segment!r} does not start with a mnemonic"
        words.append(match["word"])
    return words


@pytest.mark.parametrize("name", sorted(HANDLERS))
def test_docstring_headline(name):
    module, doc = HANDLERS[name]
    assert doc, f"{name} has no docstring"
    text = headline(doc)
    assert _CITATION.search(text), f"{name}: headline must end with its source in parentheses"
    owned = OWNERS[module]
    for word in mnemonics(doc):
        assert word in owned, f"{name} claims {word}, which {module} does not own"


def test_every_decoded_opcode_is_claimed_by_its_handler():
    for code, entry in enumerate(OPCODES):
        word = ALIASES.get(entry.mnemonic.split()[0], entry.mnemonic.split()[0])
        if code == 0xCB:
            word = "CB"
        name = HANDLER_NAMES[code]
        assert word in mnemonics(HANDLERS[name][1]), f"${code:02X} {entry.mnemonic} -> {name}"


def test_every_cb_operation_has_a_handler():
    for code, entry in enumerate(CB_OPCODES):
        word = entry.mnemonic.split()[0]
        claimed = [
            n for n, (_, d) in HANDLERS.items() if n.startswith("_cb_") and word in mnemonics(d)
        ]
        assert claimed, f"CB ${code:02X} {entry.mnemonic}: no _cb_ handler claims {word}"


def test_decode_table_names_real_handlers_and_leaves_none_dead():
    assert set(HANDLER_NAMES) <= set(HANDLERS)
    dead = {n for n in HANDLERS if n.startswith("_op_")} - set(HANDLER_NAMES)
    assert not dead, f"handlers no opcode reaches: {sorted(dead)}"
