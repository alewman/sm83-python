# Timing: every M-cycle, with its address

Units: M-cycles (4 T-cycles each; see [start-here.md](start-here.md) "Clocks").
Sources: GBCTR's per-instruction tables (`src/gb-ctr/chapter/cpu/instruction-set.typ`,
extracted by `scripts/gbctr_timing.py` into `tests/gbctr_timing.json`),
SonoSooS's *Gameboy CPU internals* (`docs/SonoSooS-DMGCPU.md`), SameBoy
`Core/sm83_cpu.c`, and SingleStepTests sm83 (`src/sm83/v1`). Tiers and
agreement are in [validation.md](validation.md).

## Agreement already measured (2026-10-05)

`tests/gbctr_timing.json` was compared with the cycle lists of all 500
SingleStepTests sm83 files: for **498 opcodes the number of M-cycles agrees on
every case, including both paths of the conditional jumps, calls and returns**.
The two exceptions are `HALT` and `STOP`, which GBCTR leaves as TODO and which
the corpus records as 3 M-cycles each, an artefact of its generator, not a
hardware fact ([undocumented-behavior.md](undocumented-behavior.md) C3).

The corpus and GBCTR **disagree on the address of internal cycles**: the corpus
writes the previous cycle's address there ("For convenience, we often just use
the last address generated", `src/sm83/README.MD`), GBCTR writes the IDU's
register or $0000. Compare reads and writes against the corpus; take internal
addresses from GBCTR (contradiction C1).

## The table, by category

Row format: one entry per M-cycle after the opcode fetch, ending with the
fetch of the next opcode (`F@x` = opcode fetch at x). `R@x` read, `W@x` write,
`I@x` internal cycle with address x. `±` marks the IDU incrementing or
decrementing that address. Taken from GBCTR verbatim; "n" in the M column is the
documented length (the count a programmer sees).

| Category | M | Cycles after the fetch |
| --- | --- | --- |
| `NOP`, `LD r,r'`, ALU r, `INC/DEC r`, rotates on A, `DAA` `CPL` `SCF` `CCF`, `DI`, `EI` | 1 | `F@PC+` |
| `LD r,n`, ALU n | 2 | `R@PC+`, `F@PC+` |
| `LD r,(HL)`, ALU (HL) | 2 | `R@HL`, `F@PC+` |
| `LD (HL),r` | 2 | `W@HL`, `F@PC+` |
| `LD (HL),n` | 3 | `R@PC+`, `W@HL`, `F@PC+` |
| `LD A,(BC/DE)` / `LD (BC/DE),A` | 2 | `R/W@BC|DE`, `F@PC+` |
| `LD A,(HL±)` / `LD (HL±),A` | 2 | `R/W@HL±`, `F@PC+` |
| `LDH A,(C)` / `LDH (C),A` | 2 | `R/W@$FF00+C`, `F@PC+` |
| `LDH A,(n)` / `LDH (n),A` | 3 | `R@PC+`, `R/W@$FF00+Z`, `F@PC+` |
| `LD A,(nn)` / `LD (nn),A` | 4 | `R@PC+`, `R@PC+`, `R/W@WZ`, `F@PC+` |
| `LD rr,nn` | 3 | `R@PC+`, `R@PC+`, `F@PC+` |
| `LD (nn),SP` | 5 | `R@PC+`, `R@PC+`, `W@WZ+` (SPL), `W@WZ` (SPH), `F@PC+` |
| `LD SP,HL` | 2 | `I@HL` (SP ← HL through the IDU), `F@PC+` |
| `PUSH rr` | 4 | `I@SP−`, `W@SP−` (high), `W@SP` (low), `F@PC+` |
| `POP rr` | 3 | `R@SP+` (low), `R@SP+` (high), `F@PC+` |
| `LD HL,SP+e` | 3 | `R@PC+`, `I@$0000`, `F@PC+` |
| `ADD SP,e` | 4 | `R@PC+`, `I@$0000`, `I@$0000`, `F@PC+` |
| `INC/DEC rr` | 2 | `I@rr±`, `F@PC+` |
| `ADD HL,rr` | 2 | `I@$0000`, `F@PC+` |
| `INC/DEC (HL)` | 3 | `R@HL`, `W@HL`, `F@PC+` |
| CB r (all) | 2 | `R@PC+` (the CB opcode, no interrupt check), `F@PC+` |
| CB `BIT b,(HL)` | 3 | `R@PC+`, `R@HL`, `F@PC+` |
| CB other (HL) | 4 | `R@PC+`, `R@HL`, `W@HL`, `F@PC+` |
| `JP nn` | 4 | `R@PC+`, `R@PC+`, `I@$0000`, `F@PC+` (PC = WZ) |
| `JP cc,nn` | 4 / 3 | taken as `JP nn`; not taken: `R@PC+`, `R@PC+`, `F@PC+` |
| `JP HL` | 1 | `F@HL+` (PC ← HL + 1) |
| `JR e` | 3 | `R@PC+`, `I@` "PCH" (GBCTR's wording; the IDU adjusts PCH), `F@WZ+` |
| `JR cc,e` | 3 / 2 | taken as `JR e`; not taken: `R@PC+`, `F@PC+` |
| `CALL nn` | 6 | `R@PC+`, `R@PC+`, `I@SP−`, `W@SP−` (PCH), `W@SP` (PCL), `F@PC+` (PC = WZ) |
| `CALL cc,nn` | 6 / 3 | taken as `CALL`; not taken: `R@PC+`, `R@PC+`, `F@PC+` |
| `RET`, `RETI` | 4 | `R@SP+`, `R@SP+`, `I@$0000`, `F@PC+` |
| `RET cc` | 5 / 2 | `I@$0000` (condition), then taken: `R@SP+`, `R@SP+`, `I@$0000`, `F@PC+`; not taken: `F@PC+` |
| `RST n` | 4 | `I@SP−`, `W@SP−` (PCH), `W@SP` (PCL), `F@PC+` (PC = n) |
| `HALT`, `STOP` | — | not in GBCTR; see below |
| 11 holes | ∞ | no further bus cycles are documented; the CPU never fetches again |

`SP−` on the `W@SP−` rows means the write happens at the already decremented
SP and the IDU decrements again; GBCTR's `idu_op` column has the exact
register transfer for each cycle.

## Interrupt dispatch

Five M-cycles from the discarded fetch to the vector fetch, in the
fetch-first model the brief chooses (SonoSooS "ISR and NMI"; Pan Docs
`Interrupts.md` "lasts 5 M-cycles"; SameBoy `GB_cpu_run`):

| # | Bus | What happens |
| --- | --- | --- |
| 1 | `R@PC+` | the opcode fetch that would have started the next instruction; its byte is discarded |
| 2 | `I@PC−` | the IDU puts PC back (SameBoy `cycle_oam_bug(gb, GB_REGISTER_PC)`) |
| 3 | `I@SP−` | SP ← SP − 1 |
| 4 | `W@SP−` | PCH; **IE is sampled after this write** (a write to $FFFF here can cancel) |
| 5 | `W@SP` | PCL; **IF is sampled after this write**; vector = lowest bit of `IE & IF & $1F`, or **$0000 if none**; IME ← 0; that IF bit cleared |

Then the handler's first opcode is fetched at the vector. The sampling points
are SameBoy's (`interrupt_queue = gb->interrupt_enable` after the high write,
`&= IF` after the low write, with a special case when the low write itself
targets $FF0F) and they are what Mooneye `ie_push` (hardware-verified on every
model) requires. Gambatte `irq_precedence/late_if_via_sp_*` (hardware-captured)
covers IF written by the push.

When is "pending" decided at all? At fetch cycles: the dispatch above replaces
the instruction whose fetch is cycle 1. With per-M-cycle callbacks the
convention is: the core decides at the start of `step()`, after the previous
M-cycle's callback has returned (so the board has already advanced that cycle's
4 T-cycles). Whether hardware samples IF a fraction of an M-cycle earlier or later
is the board's to model; Mooneye `intr_timing`, `di_timing-GS`, `ei_timing`,
`halt_ime*`, Gambatte `irq_precedence`, `halt` and dmg-sim decide it.

## EI, DI, RETI

| Instruction | IME effect | Source |
| --- | --- | --- |
| `EI` | IME ← 1 after the *next* instruction's fetch check: `EI; X` cannot be interrupted before X completes | GBCTR (`IME_next`), SonoSooS "EI and DI", Mooneye `ei_sequence`, `ei_timing` |
| `DI` | immediate; also cancels a pending `EI` | GBCTR ("cancelling any scheduled effects of the EI"), Mooneye `rapid_di_ei` |
| `RETI` | IME ← 1 immediately (no delay) | GBCTR (`RETI` pseudocode), SameBoy, Mooneye `reti_intr_timing` |
| dispatch | IME ← 0 | Pan Docs |

`EI; EI` and `EI; DI` sequences: Mooneye `ei_sequence` and `rapid_di_ei`.
SingleStepTests sm83 records `"ei": 1` in the final state of `$FB` cases (the
delayed-enable flag); compare it.

## HALT

Entry: one M-cycle that fetches the byte after HALT **without incrementing
PC** (SonoSooS: HALT's generic fetch is `IR = [PC]`). Then, per the table in
[start-here.md](start-here.md):

- halted M-cycles: the CPU does nothing; what the address bus shows is not
  documented (SameBoy advances time without an access). The core reports one
  internal cycle per halted M-cycle with address PC, flagged as halted, and the
  board decides what (if anything) that address means. Settle with dmg-sim.
- wake with IME = 1: a fetch with increment (discarded), then dispatch as above
  (SonoSooS table "wakeup from HALT mode, dummy fetch (with increment)").
- wake with IME = 0: the fetched byte executes, PC increments normally.
- HALT bug (IME = 0, pending at entry): no halted cycles; the next fetch reads
  the same address again.
- DMG vs CGB: SameBoy charges 2 extra T-cycles on DMG when leaving HALT
  (`if (gb->halted && !GB_is_cgb(gb) && !gb->just_halted) GB_advance_cycles(gb, 2)`);
  Mooneye `halt_ime1_timing2-GS` passes on DMG/MGB/SGB/SGB2 and fails on
  CGB/AGB/AGS. Sub-M-cycle, so a board concern; the core's halted-cycle
  reporting must let the board add it.

## STOP

No cycle table exists in any source. SameBoy's `stop()` reads at PC (comment:
"Timing is completely unverified, and only affects STOP triggering the OAM bug"),
then either enters stop mode, behaves as HALT, as a NOP, or switches speed
(CGB, KEY1 bit 0), and conditionally reads the second byte. SonoSooS gives the
IME = 0 cases ("STOP works, appears as 2B" / "acts as HALT, appears as 2B" /
"acts as NOP, appears as 1B" / "zombie mode"). The core implements the decode
and the PC behaviour and asks the board through the STOP hook which case applies
([the brief](handoff-brief.md)). Judges: Gambatte `speedchange` (242
hardware-captured CGB tests), SameBoy's tester, and nothing for DMG stop mode.

## CGB double speed

The board halves the CPU's M-cycle length relative to the PPU/APU (Pan Docs
`CGB_Registers.md` KEY1). The core is unaware, except that STOP is the trigger.
The speed switch's own duration (SameBoy: "speed switching takes 2 extra
T-cycles", `speed_switch_halt_countdown = 0x20008`) is board timing.
