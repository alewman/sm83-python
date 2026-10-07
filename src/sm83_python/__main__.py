"""Run a Game Boy ROM on the core in the minimal harness: ``python -m sm83_python``.

    python -m sm83_python cpu_instrs/individual/01-special.gb
    python -m sm83_python rom.gb --boot dmg_boot.bin --max-cycles 50000000
    python -m sm83_python rom.gb --trace run.jsonl --max-cycles 100000
    python -m sm83_python rom.gb --debug -c "break 0x150" -c "continue" --batch

The host is not a Game Boy: ROM with an MBC1-style bank register, RAM, serial port, DIV, and
IF/IE on the core; no timer, PPU or sound (``sm83_python.harness``). The ROM's serial output is
printed; the exit status is 0 when it ends ``Passed`` (blargg) or leaves Mooneye's pass
registers, 1 otherwise. ``--trace`` writes one JSON Line per processor boundary with every
bus cycle (docs/trace-schema.md). ``--debug`` opens the command debugger (``help`` lists the
commands); numbers are decimal, ``0x1234`` or ``$1234`` hexadecimal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sm83_python.console import CommandDebugger, CommandError, format_state
from sm83_python.debug import DebugSession
from sm83_python.harness import Harness
from sm83_python.trace import step_record_to_dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sm83_python",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("rom", type=Path, help="a Game Boy ROM image")
    parser.add_argument("--boot", type=Path, help="a 256-byte boot ROM to run from $0000")
    parser.add_argument("--max-cycles", type=int, default=100_000_000, metavar="N")
    parser.add_argument("--trace", type=Path, metavar="FILE", help="write a JSONL trace")
    parser.add_argument("--debug", action="store_true", help="open the command debugger")
    parser.add_argument("-c", "--command", action="append", default=[], help="debugger command")
    parser.add_argument("--batch", action="store_true", help="exit after the -c commands")
    args = parser.parse_args(argv)

    boot = args.boot.read_bytes() if args.boot else None
    if boot is not None and len(boot) != 0x100:
        parser.error("--boot must be a 256-byte DMG boot ROM")
    harness = Harness(args.rom.read_bytes(), boot)

    if args.debug:
        session = DebugSession(harness.cpu, peek_byte=harness.peek, track_accesses=True)
        debugger = CommandDebugger(session)
        for command in ["registers", "disassemble", *args.command]:
            print(f"sm83> {command}")
            try:
                result = debugger.execute(command)
            except CommandError as exc:
                print(f"error: {exc}")
                continue
            for line in result.lines:
                print(line)
            if result.quit:
                return 0
        if not args.batch:
            debugger.interact(sys.stdin, sys.stdout)
        return 0

    trace_file = args.trace.open("w") if args.trace else None
    try:
        step = None
        if trace_file is not None:
            import json

            session = DebugSession(
                harness.cpu, peek_byte=harness.peek, history_limit=0, track_accesses=True
            )

            def step() -> int:
                record = session.step()
                encoded = json.dumps(
                    step_record_to_dict(record), separators=(",", ":"), sort_keys=True
                )
                trace_file.write(encoded + "\n")
                return record.m_cycles

        result = harness.run(max_cycles=args.max_cycles, step=step)
    finally:
        if trace_file is not None:
            trace_file.close()
    sys.stdout.write(result.text)
    if result.text and not result.text.endswith("\n"):
        sys.stdout.write("\n")
    verdict = "mooneye PASS" if result.mooneye_passed else ""
    print(
        f"[{result.reason} after {result.cycles} M-cycles, {result.instructions} instructions"
        f"{'; ' + verdict if verdict else ''}]",
        file=sys.stderr,
    )
    print(*format_state(harness.cpu.capture_state()), sep="\n", file=sys.stderr)
    return 0 if result.mooneye_passed or result.text.rstrip().endswith("Passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
