# Start here: the SM83 as a core author needs it

The Game Boy's CPU is a Sharp **SM83** core inside the system-on-a-chip that
Nintendo labelled DMG-CPU (and later CPU CGB, CPU AGB, ...). "LR35902" is
the name of the whole DMG chip, not of the CPU; GBCTR §"Introduction to the
Sharp SM83 CPU core" and `gb-research/sm83-cpu-core/README.markdown` give the
evidence for the name (Sharp's 1990 and 1996 microcomputer data books list SM83
as the core of the SM8320 and SM8311-15). This repository builds the core
alone. The board (`/data/emu/gameboy-python`) owns everything else on the
chip: PPU, APU, timer, serial, joypad, DMA, boot ROM and memory map.

Paths: `src/X` is `reference/src/X`, `docs/X` is `reference/docs/X`, `roms/X`
is `reference/roms/X`, all filled by `scripts/fetch_references.py`. Each source's
tier is in [validation.md](validation.md); cycle detail is in
[timing.md](timing.md), quirks and contradictions in
[undocumented-behavior.md](undocumented-behavior.md).

## Registers

| Register | Width | Notes |
| --- | --- | --- |
| A, F | 8 + 8 (AF) | F holds **Z N H C in bits 7–4; bits 3–0 always read 0**. `POP AF` drops them (SameBoy `pop_rr`: `af &= 0xFFF0`; Mooneye `acceptance/bits/reg_f`, verified on DMG through AGS). |
| B, C, D, E, H, L | 8 each, paired as BC, DE, HL | |
| SP, PC | 16 | |
| IR | 8 | instruction register: the opcode being executed (GBCTR §"Simple CPU core model") |
| IE | 8 | the interrupt-enable register **is in the CPU core** per GBCTR's model ("the special-purpose 8-bit registers Instruction Register (IR) and Interrupt Enable (IE)"); it is mapped at $FFFF |
| WZ | 16 | internal temporary (GBCTR's tables: `Z ← mem`, `W ← mem`); not visible to programs, but it drives the address bus on some cycles (`LD A,(nn)`, `JR`) |
| IME | 1 | interrupt master enable; not readable; set by `EI` (delayed), `RETI` (immediate), cleared by `DI` and by dispatch |

There is no I, R, IX, IY, no shadow set, no I/O space, and no S or P/V flag
(Pan Docs `CPU_Comparison_with_Z80.md`). `IF` ($FF0F, the interrupt request
latches) lives in the SoC outside the core, but the core samples it at exact
cycles; see "Interrupts" below and [the brief](handoff-brief.md) for who owns
the bits.

Flag rules per instruction: Pan Docs `CPU_Instruction_Set.md` and GBCTR's
per-instruction `flags:` fields; `gb-opcodes/Opcodes.json` has them as data.
DAA is described in [undocumented-behavior.md](undocumented-behavior.md).

## Instruction set

- **Unprefixed**: 256 opcodes, of which **11 are holes** that lock the CPU:
  `$D3 $DB $DD $E3 $E4 $EB $EC $ED $F4 $FC $FD` (Pan Docs
  `CPU_Instruction_Set.md` l.173). `$CB` is the prefix.
- **CB-prefixed**: all 256 defined (rotates/shifts/SWAP, BIT, RES, SET on
  B C D E H L (HL) A).
- Machine-readable sources: `gb-opcodes/Opcodes.json` (mnemonic, bytes, cycles,
  operands, flags, CC0) and GBCTR's `opcodes.toml` + per-category timing
  (`scripts/gbctr_timing.py` turns the latter into `tests/gbctr_timing.json`).
  Generate the dispatch table from them, as m6800-python generated its map
  from Motorola's appendix; hand-write the handlers.
- Opcode blocks (Pan Docs): block 0 (`00xxxxxx`) misc/16-bit/INC/DEC/LD r,n/
  rotates-on-A/JR; block 1 (`01xxxxxx`) `LD r,r'` with `$76` = HALT; block 2
  (`10xxxxxx`) 8-bit ALU on r; block 3 (`11xxxxxx`) control flow, stack, LDH,
  ALU on n, RST, `$CB`, `EI`/`DI`, the holes.

## Clocks and the M-cycle

The bus does one access per **M-cycle** (machine cycle) = 4 **T-cycles**
(the 4.194304 MHz master clock on DMG; M-cycle rate 1.048576 MHz).
GateBoy's README and GBCTR's timing diagrams split each M-cycle into 8 clock
phases; the CPU's own model only needs M-cycles. On CGB in double-speed mode
the CPU's M-cycle takes 2 master-clock ticks instead of 4 while the PPU keeps
its rate: the **board** scales time, the core does not change.

Every count in this repository's documents is in M-cycles unless it says T.
GBCTR, SingleStepTests sm83 and Mooneye all count M-cycles; MAME's
`totalcycles` and Pan Docs' tables count T-cycles (4 per M).

## Fetch/execute overlap (the shape of `step`)

GBCTR §"CPU core timing" / "Fetch/execute overlap": the **opcode fetch of the
next instruction happens on the last M-cycle of the current one**. An
instruction "of length n" occupies n M-cycles from its first execute cycle up
to and including the fetch of its successor. Consequences the core must
model:

- `JP HL` is one M-cycle: its single cycle *is* the fetch at HL (GBCTR `JP_hl`:
  address HL, `PC ← HL + 1`).
- Interrupt dispatch begins at a fetch: the opcode just fetched is discarded
  and PC is decremented (SonoSooS "ISR and NMI"; GBCTR's `fetch_cycle()` returns
  `IR, intr`).
- `HALT` fetches without incrementing PC (`IR = [PC]`), which is the root of the
  HALT bug (SonoSooS "HALT"; nitro2k01 `double-halt-cancel`).
- `$CB` is an instruction whose last cycle fetches the CB opcode *without* the
  interrupt check, so CB instructions are uninterruptible two-byte opcodes
  (SonoSooS "$CB prefix").
- The 11 holes never reach a fetch, so nothing (not even interrupts) restarts
  the CPU (SonoSooS "Opcode holes"; Gambatte `hwtests/undef_ops/*_dmg08_cgb04c_out01`:
  hardware-captured on DMG and CGB, the VBlank handler never runs).

A core may present this either way, as long as every bus access happens on
the right M-cycle in the right order: (a) "fetch-decode-execute" where `step()`
begins with the opcode read (SingleStepTests sm83 records cycles this way:
first entry is the fetch at PC), or (b) GBCTR's overlapped form where `step()`
ends with the next fetch (adtennant's v2 corpus is "decode-execute-prefetch").
[The brief](handoff-brief.md) picks (a) and says why.

## The bus as the SoC sees it

Per GBCTR and SonoSooS, **every M-cycle drives a 16-bit address**, even when
nothing is read or written: the IDU (the 16-bit increment/decrement unit) sits
on the address bus, so `INC rr`, `DEC rr`, `PUSH`'s pre-decrement, `LD SP,HL`
and the rest put a register's value on the bus during their "internal" cycles,
and cycles that use neither IDU nor memory put **$0000** there (GBCTR:
`ADD HL,rr` M2, `JP nn` M4, `RET` M4, `ADD SP,e` M3–M4, `LD HL,SP+e` M3). The
DMG's PPU sees those addresses: the OAM corruption bug is the SoC reacting to
an IDU address in $FE00–$FEFF during OAM scan, with or without a read or write
(Pan Docs `OAM_Corruption_Bug.md` "Accurate Description"). So the core's bus
contract carries three kinds of M-cycle, each with its address:

| Kind | GBCTR `mem_rw` | Example |
| --- | --- | --- |
| read | `R: ...` / opcode | operand, `(HL)`, stack pop, fetch |
| write | `W: ...` | `(HL)`, stack push, `LDH (n),A` |
| internal | `U` | `INC rr` M2 at rr; `PUSH` M2 at SP; `ADD HL,rr` M2 at $0000 |

and whether the IDU incremented or decremented the address on that cycle
(Pan Docs lists the read-plus-increment cases, `LD A,(HL+)`, as a different
corruption pattern from a plain read). The full per-category table is
`tests/gbctr_timing.json`; [timing.md](timing.md) summarises it.

## Interrupts

Five sources, bits 0–4 of IE and IF, vectors $40 VBlank, $48 STAT, $50 Timer,
$58 Serial, $60 Joypad; lowest bit wins (Pan Docs `Interrupts.md`). Upper three
bits of IF read 1 on hardware (Mooneye `if_ie_registers`; board detail).

- Pending = `IE & IF & $1F` ≠ 0. Dispatch needs IME = 1 as well.
- **Dispatch takes 5 M-cycles** (Pan Docs, citing SonoSooS): M1 the discarded
  fetch with `PC ← PC − 1` via the IDU, M2 internal with `SP ← SP − 1` (address
  SP), M3 write PCH to SP−1, M4 write PCL to SP−2 and load the vector, M5 the
  fetch at the vector. [timing.md](timing.md) has the bus row by row.
- **The vector is chosen late.** If the high-byte push (M3) writes IE ($FFFF)
  and clears the pending bit, the dispatch is cancelled and **PC becomes $0000**;
  the low-byte push (M4) is too late to cancel (Mooneye
  `acceptance/interrupts/ie_push`, verified on DMG, MGB, SGB, SGB2, CGB, AGB,
  AGS). A higher-priority interrupt arriving before the vector is chosen wins
  (SonoSooS: "PC is only written in M3"). IME is cleared and the chosen IF bit
  is cleared; on cancellation IF is left alone (`ie_push` round 1, "IF modified").
- **EI** takes effect after the following instruction: `EI; DI` lets nothing
  in; `EI; NOP` lets an interrupt in after the NOP (GBCTR `EI` "Schedules
  interrupt handling to be enabled after the next machine cycle"; Mooneye
  `ei_sequence`, `ei_timing`, `rapid_di_ei`). **DI** is immediate. **RETI**
  sets IME with no delay (GBCTR, SameBoy, Mooneye `reti_intr_timing`).
- Interrupts are checked at fetch cycles only, and not at the fetch that ends
  `$CB` (SonoSooS).

## HALT

`HALT` stops instruction execution until `IE & IF & $1F` ≠ 0, whatever IME is
(Pan Docs `halt.md`). The four cases (SonoSooS "HALT" table; Pan Docs; SameBoy
`halt()`):

| IME | Pending when HALT executes? | Result |
| --- | --- | --- |
| 1 | no | halt; on wake, dispatch; RETI returns to the instruction after HALT |
| 1 | yes | no halt; dispatch happens **at HALT**, so the handler returns to the HALT, which then halts properly (SameBoy: `pc--`) |
| 0 | no | halt; on wake, continue after HALT without dispatch |
| 0 | yes | **HALT bug**: no halt, and the next fetch does not increment PC, so the byte after HALT is read twice (`rst` after it pushes its own address; nitro2k01). `EI; HALT` with a pending interrupt dispatches and returns to the HALT (SameSuite `interrupt/ei_delay_halt`). |

SameBoy states the bug also happens on CGB in both modes (comment in `halt()`).
Wake-up timing differs between DMG and CGB in SameBoy (`GB_cpu_run`: extra
2 T-cycles on DMG) and Mooneye's `halt_ime1_timing2-GS` passes on DMG/SGB only;
the core exposes the halted state and lets the board own the sub-M-cycle
difference ([undocumented-behavior.md](undocumented-behavior.md) item U7).

## STOP

`$10`. Not decoded as two bytes: it behaves as one byte that *appears* to be
two when it stops, because waking performs a fetch (SonoSooS "NOP and STOP").
Its result depends on the joypad lines (P10–P13), on whether an interrupt is
pending, on IME, and on CGB on KEY1 bit 0 (speed switch). SonoSooS gives the
IME = 0 table; SameBoy `stop()` encodes the full CGB behaviour; Pan Docs
reproduces LIJI's flowchart (`pandocs/src/imgs/stop_diagram.svg`). No licensed
game uses STOP except to switch CGB speed (Pan Docs
`Reducing_Power_Consumption.md`). GBCTR's STOP section is TODO. The core
cannot decide STOP alone (it needs the joypad, KEY1, DIV reset): it reports
"STOP executed, pending = …" to the board through a hook and lets the board
choose the outcome ([the brief](handoff-brief.md)).

## Reset and power-on

The core starts with PC = $0000 executing the boot ROM; the boot ROM sets the
registers the cartridge sees at $0100 (Pan Docs `Power_Up_Sequence.md` "CPU
registers", per model). That is the board's concern: the core provides plain
register attributes and a `reset()` that sets PC = 0, IME = 0, IE = 0 and no
pending EI. Power-on values of the other registers are not documented by a
hardware source; leave them at 0 and settable.

## What the core does not own

PPU, APU, timer/DIV, serial, joypad, OAM DMA (the CPU keeps running from HRAM
during it: Pan Docs `OAM_DMA_Transfer.md`), CGB HDMA (stalls the CPU), the boot
ROM and its disable register, the memory map, open-bus values, the OAM
corruption bug's effect, double-speed clocking, the DMG/CGB HALT wake
difference. The core must **expose** enough for the board to do each of them
exactly: per-M-cycle bus callbacks with internal cycles, IDU direction, a
halted/stopped state, a STOP hook, and IE/IF sampled at documented points.
