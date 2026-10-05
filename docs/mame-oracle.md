# MAME 0.285 as an emulator-derived detector for the SM83

MAME's `lr35902` device (`src/devices/cpu/lr35902/`, the Game Boy drivers in
`src/mame/nintendo/gb.cpp`) runs real Game Boy code with a whole board around
it. It is **emulator-derived**: use it to find where a core first disagrees on
ordinary code, then settle the disagreement with a higher tier
([validation.md](validation.md)). It is **known wrong** on three
hardware-verified tests (below), so it is never a referee for HALT, EI, or
interrupt dispatch.

Everything on this page was run on 2026-10-05 on this machine, MAME 0.285 at
`/usr/games/mame`. `scripts/mame_trace.py` is the recipe as a script.

## The boot ROM problem, solved without a Nintendo dump

`mame -listroms gameboy` requires `dmg_boot.bin` (CRC 59c8598e) and lists
`dmg_v0.rom`; none is installed here, and none is fetched. MAME refuses to start
when a required ROM is missing, but **runs with a wrong-checksum substitute**
after printing `dmg_boot.bin WRONG CHECKSUMS ... WARNING: the machine might not
run correctly`. Two free substitutes work:

| Boot ROM | From | Reaches $0100 at `totalcycles` | Registers at $0100 |
| --- | --- | --- | --- |
| SameBoy `dmg_boot.bin` (MIT, built by `scripts/build_referees.py sameboy`) | `src/SameBoy/BootROMs` | 5,881,108 (it animates the logo) | A=01 F=B0 B=00 C=13 D=00 E=D8 H=01 L=4D SP=FFFE, IE=00 IF=01 |
| dmg-sim `boot/quickboot.bin` (CC-BY-SA-4.0) | `src/dmg-sim/boot` | 633,796 | the same |

Real Nintendo boot ROMs are also available locally (paths and hashes in
`/data/emu/gameboy-python/docs/start-here.md` "Boot ROMs"; DMG Rev 1 is MAME's
`dmg_boot.bin`, SHA-1 `4ed31ec6…`). Optional for rung 4: put one under the
run's `roms/gameboy/` to get real boot timing without the checksum warning.
Never commit it. The free substitutes remain the script's default.

Both free ROMs hand over the DMG register values Pan Docs lists (`Power_Up_Sequence.md`,
"DMG" column). The script uses SameBoy's; give it a different file with the
same name under `roms/gameboy/` to use quickboot. A trace begins in the boot
ROM: compare from the first line with PC = $0100.

Driver names: `gameboy` (DMG), `gbpocket` (MGB, `mgb_boot.bin`), `gbcolor`
(CGB, `gbc_boot.1` + `gbc_boot.2`, not wired in the script), `supergb`.

## The recipe

Write `trace.lua` in a fresh working directory:

```lua
local dbg = manager.machine.debugger
dbg.visible_cpu = manager.machine.devices[":maincpu"]
dbg:command('trace cpu.trace,,noloop,{logerror "%X %X %X %X %X %X %X %X %X %X %X %X %d\n",pc,a,f,b,c,d,e,h,l,sp,ie,if,totalcycles}')
dbg:command('wpset ff01,1,w,1,{logerror "SB %X %d\n",wpdata,totalcycles; g}')
dbg:command("go")
```

and run, from that directory, with the boot ROM at `roms/gameboy/dmg_boot.bin`
and the cartridge copied in as `cart.gb`:

```text
mame gameboy -rompath roms -cart cart.gb -homepath "$PWD" \
  -video none -sound none -nothrottle -noreadconfig -skip_gameinfo \
  -debug -debugger none -log -seconds_to_run 3 -autoboot_script "$PWD/trace.lua"
```

`error.log` lands in the working directory (as on every board in this family).
Its first line starts with a UTF-8 byte-order mark, followed by cartridge-slot
and header lines from MAME; then one line per instruction (before it executes)
and `SB` lines for serial writes, which is where blargg's and Mooneye's ROMs
print.

Verified run: blargg `cpu_instrs/individual/06-ld r,r.gb`, 3 emulated seconds,
10.2 s wall, **1,121,511 instruction lines**, serial text
`'06-ld r,r\n\n\nPassed\n'`.

## Facts about the trace

- Device `:maincpu`, shortname `lr35902`, "Sharp LR35902". State symbols (from
  Lua `cpu.state`): `A B C CURFLAGS CURPC D E F GENPC H IE IF IRQ L PC SP`.
  **There is no IME symbol.**
- `totalcycles` counts **T-cycles**: consecutive NOPs differ by 4. Divide by 4
  for M-cycles.
- Other devices: `:ppu` (`dmg_ppu`), `:apu` (`dmg_apu`), `:cartslot`.
- The family's trace traps hold here too: keep `logerror` actions to at most 14
  values (13 used); `-debugger none` is required; Lua notifier subscriptions
  must be held in globals or they stop firing.
- For a result without the debugger: `scripts/mame_trace.py ... --no-trace`
  takes a PNG snapshot at the last frame (`manager.machine.video:snapshot()`
  from a frame notifier) and exits.

## How MAME 0.285 scores (screenshots after 60 emulated seconds)

| ROM | MAME 0.285 | Tier of the ROM |
| --- | --- | --- |
| blargg `cpu_instrs` (all 11) | Passed all tests | hardware-corrected |
| blargg `instr_timing` | Passed | hardware-corrected |
| blargg `mem_timing` | Passed all tests | hardware-corrected |
| blargg `halt_bug` | **Failed** (DE always $0411: no double fetch) | hardware-corrected |
| Mooneye `instr/daa` | Test OK | hardware-verified |
| Mooneye `di_timing-GS`, `halt_ime0_ei`, `intr_timing`, `push_timing`, `rapid_di_ei` | Test OK / assertions OK | hardware-verified |
| Mooneye `ei_sequence` | **FAIL: NO INTR** | hardware-verified |
| Mooneye `interrupts/ie_push` | **R1: not cancelled** | hardware-verified |

So: MAME agrees with hardware on instruction semantics and ordinary timing,
and lacks the HALT bug, an EI-sequence case, and IE-push cancellation.

## Use

1. Rung 4 of [validation.md](validation.md), **replay**: real code reads I/O
   registers (LY, STAT, DIV, IF, JOYP) whose values come from the board, so a
   core in the minimal harness diverges from MAME at the first `LDH A,($44)`.
   Make the replay board-free by adding one more watchpoint to the recipe,
   `wpset ff00,100,r,1,{logerror "R %X %X %d\n",wpaddr,wpdata,totalcycles; g}`
   (I/O, HRAM and IE reads), and have the harness answer every read in
   $FF00–$FFFF from that log, in order, instead of from its own model. Writes
   are compared, not obeyed. Then compare `PC A F B C D E H L SP` per
   instruction from PC = $0100 and the `totalcycles` deltas ÷ 4. Not yet run:
   the extra watchpoint's volume (every HRAM read) should be measured first; if
   it is large, restrict it to $FF00–$FF7F and $FFFF and let the harness keep
   HRAM.
2. The first divergence is a lead, not a verdict: look it up in
   [undocumented-behavior.md](undocumented-behavior.md), then ask a higher tier.
3. Interrupt entries are visible in the trace as a jump to $40–$60 without a
   call; the replayed core must take them at the same instruction, which only
   works if IF/IE reads and the core's own sampling agree. Divergence there is
   expected on the cases MAME gets wrong (table above).
