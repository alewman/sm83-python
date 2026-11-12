#!/usr/bin/env python3
"""Record MAME 0.285's per-instruction SM83 trace of a Game Boy ROM.

Runs the recipe in docs/mame-oracle.md in a fresh directory (default
``tests/mame_traces/<driver>-<rom stem>``, gitignored) and leaves ``error.log``
there. MAME's Game Boy drivers refuse to start without a boot ROM, and no
Nintendo boot ROM is fetched here: the script gives MAME SameBoy's free boot
ROM (built by scripts/build_referees.py) under the expected file name, and
MAME runs it after a WRONG CHECKSUMS warning.

    python scripts/mame_trace.py gameboy "reference/src/gb-test-roms/cpu_instrs/individual/06-ld r,r.gb"
    python scripts/mame_trace.py gameboy reference/src/gb-test-roms/halt_bug.gb --no-trace --seconds 30

``error.log`` then holds, in execution order:

- one line per instruction, before it executes, all hex except the last:
  ``PC A F B C D E H L SP IE IF totalcycles``; ``totalcycles`` counts T-cycles
  (4 per M-cycle: a NOP advances it by 4), from power-on of the boot ROM;
- ``SB value totalcycles`` for every write to $FF01 (the serial data
  register, where blargg's and Mooneye's ROMs print);
- with ``--io``, ``R address data totalcycles`` for every read of $FF00-$FFFF, in
  order, after the line of the instruction that made it.

MAME saves a PNG of the screen under ``snap/<driver>/`` at frame ``--snapshot``
(default: the last whole frame of ``--seconds``; the DMG runs 59.73 frames a
second) and exits.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# $MAME, else `mame` on PATH, else Debian's location.
MAME = os.environ.get("MAME") or shutil.which("mame") or "/usr/games/mame"
SAMEBOY_BOOT = ROOT / "reference" / "src" / "SameBoy" / "build" / "bin" / "tester"

# driver -> (MAME's boot ROM file name, SameBoy's free substitute)
DRIVERS = {
    "gameboy": ("dmg_boot.bin", "dmg_boot.bin"),
    "gbpocket": ("mgb_boot.bin", "dmg_boot.bin"),
    "gbcolor": ("gbc_boot.1", None),  # CGB boot ROM is split in two in MAME; not wired yet
}

# A logerror action silently drops lines past 14 values (found on the Z80
# boards); 13 here. MAME 0.285's lr35902 state symbols are
# A B C D E F H L PC SP IE IF IRQ CURPC GENPC CURFLAGS (no IME).
TRACE_LUA = """\
local dbg = manager.machine.debugger
dbg.visible_cpu = manager.machine.devices[":maincpu"]
dbg:command('trace cpu.trace,,noloop,{logerror "%X %X %X %X %X %X %X %X %X %X %X %X %d\\\\n",\
pc,a,f,b,c,d,e,h,l,sp,ie,if,totalcycles}')
dbg:command('wpset ff01,1,w,1,{logerror "SB %X %d\\\\n",wpdata,totalcycles; g}')
dbg:command("go")
"""

# --io adds every read of $FF00-$FFFF (I/O registers, HRAM and IE), in order, for the replay
# (sm83_python.replay): ``R address data totalcycles`` lines between the instruction lines.
IO_LUA = """\
dbg:command('wpset ff00,100,r,1,{logerror "R %X %X %d\\\\n",wpaddr,wpdata,totalcycles; g}')
"""

# Notifier subscriptions are unsubscribed when garbage-collected: keep them in
# globals, or the callbacks silently stop.
SNAP_LUA = """\
local frames = 0
snap_sub = emu.add_machine_frame_notifier(function()
  frames = frames + 1
  if frames == {frame} then
    manager.machine.video:snapshot()
    manager.machine:exit()
  end
end)
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("driver", choices=sorted(d for d, (_, sub) in DRIVERS.items() if sub))
    parser.add_argument("rom", type=Path)
    parser.add_argument("--seconds", type=int, default=3, help="emulated seconds")
    parser.add_argument("--no-trace", action="store_true", help="no debugger: result only")
    parser.add_argument("--io", action="store_true", help="also log reads of $FF00-$FFFF")
    parser.add_argument("--snapshot", type=int, metavar="FRAME")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--mame", default=MAME)
    args = parser.parse_args()
    rom = args.rom.resolve()
    out = (args.out or ROOT / "tests" / "mame_traces" / f"{args.driver}-{rom.stem}").resolve()
    if out.exists():
        shutil.rmtree(out)
    boot_name, substitute = DRIVERS[args.driver]
    boot = SAMEBOY_BOOT / substitute
    if not boot.exists():
        raise SystemExit(f"{boot} missing: run scripts/build_referees.py sameboy")
    (out / "roms" / args.driver).mkdir(parents=True)
    shutil.copyfile(boot, out / "roms" / args.driver / boot_name)
    shutil.copyfile(rom, out / "cart.gb")
    lua = ""
    if not args.no_trace:
        lua = TRACE_LUA
        if args.io:  # the watchpoint goes in before "go"
            lua = lua.replace('dbg:command("go")', IO_LUA + 'dbg:command("go")')
    lua += SNAP_LUA.format(frame=args.snapshot or int(args.seconds * 59.73) - 1)
    (out / "trace.lua").write_text(lua, encoding="utf-8")
    version = subprocess.run(
        [args.mame, "-version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    debug = [] if args.no_trace else ["-debug", "-debugger", "none"]
    began = time.monotonic()
    # error.log lands in the working directory, not under -homepath.
    subprocess.run(
        [args.mame, args.driver, "-rompath", "roms", "-cart", "cart.gb",
         "-homepath", str(out), "-snapshot_directory", "snap",
         "-video", "none", "-sound", "none", "-nothrottle",
         "-noreadconfig", "-skip_gameinfo", *debug, "-log",
         "-seconds_to_run", str(args.seconds), "-autoboot_script", str(out / "trace.lua")],
        cwd=out, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    wall = time.monotonic() - began
    instructions = 0
    serial = bytearray()
    with (out / "error.log").open("rb") as log:
        for line in log:
            fields = line.split()
            if line.startswith(b"SB ") and len(fields) == 3:
                serial.append(int(fields[1], 16))
            elif len(fields) == 13 and fields[0][:1].isalnum():
                instructions += 1
    print(f"MAME {version}, {args.driver}, {wall:.1f} s wall: {out / 'error.log'}")
    if not args.no_trace:
        print(f"  {instructions:,} instructions")
        print(f"  serial: {serial.decode('ascii', 'replace')!r}")
    for snap in sorted((out / "snap").rglob("*.png")):
        print(f"  snapshot: {snap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
