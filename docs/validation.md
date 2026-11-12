# Validation: every oracle, its tier, and the plan

## Oracle tiers

The family's rule (z80-python `docs/validation.md`): rank an oracle by **where
its expected values came from**; a lower tier detects, the highest tier that
covers a claim decides it.

| Tier | Meaning here |
| --- | --- |
| **hardware-captured** | the expected values were recorded on real consoles (Gambatte's `_dmg08_`/`_cgb04c_` outputs) |
| **hardware-verified** | a self-checking ROM whose pass condition the author confirmed on named hardware (Mooneye: per-test "Verified results" lines; blargg: CRCs/expectations from his devcart runs) |
| **die-traced** | a model built from photographs of the chip (Gekkio's VHDL SM83, msinger's dmg-sim netlist). As good as the tracing; checked against the tiers above. A judge where it agrees with them, a strong detector elsewhere |
| **research documentation** | GBCTR, SonoSooS, Pan Docs: written from hardware experiments and die study, not all of it traceable to a published test |
| **emulator-derived** | values produced by an emulator (SingleStepTests sm83 via JSMoo/Ares, MAME, SameBoy, gbit). Detectors only |
| **unknown** | generator not stated (adtennant v2). Detector of last resort |

## The oracles

### SingleStepTests `sm83` — emulator-derived, the volume detector

- Pin: `SingleStepTests/sm83` @ `f9c30210245dd691661db39f5ace022c465ecc2f`
  (2024-05-10), MIT, 107 MB, `v1/*.json`.
- **500 files × 1,000 cases** = 244 unprefixed opcodes (256 minus the 11 holes
  and `$CB`) + 256 CB opcodes. Each case: initial and final `a b c d e f h l pc
  sp ime` (+ `ie` initial, ignored; `ei` final for `$FB`), sparse RAM, and a
  `cycles` list with one `[address, data, "rwm"]` sample per M-cycle, the
  opcode fetch first.
- Provenance (its `README.MD`): "These tests were created by translating Ares'
  SM83 core"; the author's emulator "passes all of Blarg's CPU instruction
  tests". So: emulator-derived, from Ares, through JSMoo.
- Measured here (2026-10-05):
  - its per-opcode **cycle counts agree with GBCTR on 498/500 files**, every
    case, both paths of conditionals (not `76` HALT, `10` STOP: C3);
  - its **read/write/internal sequence agrees with GBCTR on all 498,000 cases**
    of those 498 files;
  - on internal (`---`) cycles it records the previous address, not the IDU's
    (C1); `0` of 500,000 initial states has F's low nibble set (U1), but
    `f1.json` (POP AF) loads low bits from RAM in 932 cases and clears them in
    all.
- Use: rung 1, with internal-cycle addresses masked and `76`/`10` excluded.

### adtennant `sm83-test-data` v2 — unknown provenance

- Pin: `adtennant/sm83-test-data` @ `d1c8fd48c9e5`, MIT, sparse `/v2/` (11 MB).
- 242 files, 100 cases per opcode (CB 25,600), TomHarte format,
  decode-execute-prefetch order; omits STOP, HALT, EI, DI. Generator not
  stated. A second opinion on registers only.

### GBCTR — research documentation (die-informed), the bus judge until rung 5

- Pin: `Gekkio/gb-ctr` @ `5ce83a107013` (2026-08-16), CC-BY-SA-4.0; PDF build of
  2026-08-15 (`reference/docs/gbctr.pdf`, 176 pages).
- Per-category per-M-cycle tables for every instruction except HALT, STOP
  (TODO in the source), DAA's semantics (TODO; its timing is there), and the
  undefined opcodes. `scripts/gbctr_timing.py` extracts 101 categories.
- Its `mem_rw` row is a label row offset by one cycle and once inconsistent
  (C5); use the data row.

### SonoSooS, Pan Docs — research documentation

- SonoSooS *Gameboy CPU internals*, gist rev `8efa6645` (2023-06-27): fetch
  model, HALT/STOP tables, ISR cycles, opcode holes, NMI claim (U13).
- Pan Docs @ `0191af06ac49` (2026-10-03), CC0: instruction set, interrupts,
  halt, OAM bug, STOP flowchart, power-up registers.

### blargg's test ROMs — hardware-verified

- Pin: `retrio/gb-test-roms` @ `c240dd7d700e` (2015 mirror; no licence stated).
- `cpu_instrs` (11 sub-tests; CRC of each instruction's outputs over chosen
  inputs, compared with values from hardware), `instr_timing`, `mem_timing`,
  `mem_timing-2`, `halt_bug`, `interrupt_time` (CGB), `oam_bug` (DMG).
- Output: text on screen **and** on the serial port (SB/SC); `cpu_instrs` has
  no machine-readable result beyond the text ("Passed"/"Failed").
- **Board-free**: `cpu_instrs` 01 and 03–11 need only ROM, RAM, LY and SB/SC
  (Gekkio's die model runs them on a mock SoC, `gb-research` README).
  02 needs the timer (on the die model's mock SoC it prints "Timer doesn't
  work / Failed #4", run here). Everything else needs the timer or the PPU:
  rung 6.

### Mooneye Test Suite — hardware-verified

- Pin: source `Gekkio/mooneye-test-suite` @ `31510e12eea6` (2026-07-14), MIT;
  built ROMs `mts-20260714-0944-31510e1.zip` (SHA-256 `18aa2946…`) from
  gekkio.fi at the same revision.
- Every test's source names the models it passes and fails on ("Verified
  results"); the README lists the 18-device test fleet (DMG-CPU 0/A/B/C, MGB,
  SGB, SGB2, CGB 0–E, AGB, AGS).
- Result protocol: pass = B,C,D,E,H,L = 3,5,8,13,21,34 then `LD B,B`; fail = all
  $42; the same bytes go out over serial with busy-wait (no serial IRQ needed).
- CPU-relevant tests and their verified models:

| Test | Verified pass | Needs | Board-free on the die model's mock SoC (run here) |
| --- | --- | --- | --- |
| `instr/daa` | DMG … AGS | — | **pass** (100.6 s, 643,156 instructions) |
| `bits/reg_f` | DMG … AGS | — | **pass** (130 s) |
| `interrupts/ie_push` | DMG … AGS | IF/IE, LY | **pass** (162 s) |
| `reti_intr_timing` | DMG … AGS | IF/IE | **fail** (all $42): cause not investigated; mock-SoC IF latch or model gap |
| `if_ie_registers`, `ei_sequence`, `ei_timing`, `rapid_di_ei`, `intr_timing` | DMG … AGS | IF/IE and the serial port | **did not finish**: they wrote $00 to SB in an endless loop until killed after ~35 min (cause not traced; the mock SoC's SC is a constant $7F and has no serial interrupt). Need a harness with a serial port that completes and interrupts, or the board |
| `halt_ime0_ei`, `di_timing-GS`, `reti_timing` | see sources | LY/vblank waits | **did not finish** in ~35 min (LY is a constant $90 on the mock SoC) |
| `halt_ime1_timing` | DMG … AGS | TIMA/TAC | **timeout** at the 60 s simulated watchdog (581 s wall): needs the timer |
| `*_timing` (call, jp, ret, rst, push, pop, add_sp_e, ld_hl_sp_e) | DMG … AGS | OAM DMA as a timer | board (rung 6) |
| `halt_ime0_nointr_timing`, `halt_ime1_timing2-GS`, `div_timing` | see sources | DIV | board |

### Gambatte hardware tests — hardware-captured

- Pin: `pokemon-speedrunning/gambatte-core` @ `5a41a68c2540`, GPL-2.0, sparse
  `/test/` (the original `sinamas/gambatte` is now private: its GitHub repo is a
  README only).
- 3,524 `.asm` tests in `test/hwtests/`, each file name carrying the expected
  output captured on a **DMG (dmg08)** and/or **CGB (cgb04c)**:
  `..._dmg08_cgb04c_outXX` (same on both), `..._dmg08_outXX_cgb04c_outYY`, or
  `..._outaudio0/1`; `testrunner.cpp` reads the result as hex digits drawn on
  screen. `test/qdgbas.py` (a small Python assembler) builds them.
- CPU-relevant directories: `undef_ops` (10, U3), `halt` (89), `irq_precedence`
  (44, incl. `late_if_via_sp`), `speedchange` (242, CGB STOP), `tima`, `div`.
  All need the board (they print through the PPU): rung 6, through
  gameboy-python.

### SameSuite — hardware research ROMs

- Pin: `LIJI32/SameSuite` @ `f15645fb049a`; `interrupt/ei_delay_halt.asm` (U5);
  APU/DMA/PPU tests for the board. Needs rgbds and the board.

### Die-traced models

**Gekkio's VHDL SM83** (`Gekkio/gb-research` @ `59088f486f57`,
`sm83-cpu-core/hdl`, CC0 / MIT OR Apache-2.0): traced from an SGB-CPU 01 die
(the same SoC as DMG-CPU B). Medium-abstraction, non-synthesizable VHDL; GHDL
+ VUnit. Its README claims cpu_instrs (except 02) and Mooneye daa on a mock SoC.
Verified here 2026-10-05 with GHDL 7.0.0-dev from oss-cad-suite 2026-10-05:

- `task.py decoder_dump` writes the die's decoder states (32,768 rows, 8.6 s):
  a die-derived source for the opcode → M-cycle control signals;
- `task.py rom <rom>` ran Mooneye `daa` (pass, 100.6 s wall, ~6,400
  instructions/s), `reg_f`, `ie_push` (pass), `reti_intr_timing` (**fail**,
  although hardware passes: the die model or its mock SoC is wrong there), blargg
  `01-special` (Passed, 1,455,889 instructions, 355 s) and `02-interrupts`
  (fails for lack of a timer, as its README says). Mooneye table above.

Not independent of GBCTR (same author). The way to get die-derived internal-
cycle addresses for every opcode (C1, U12): a VUnit testbench that loads
SingleStepTests-style initial states and logs the address bus per M-cycle
(rung 5).

**msinger's dmg-sim** (`msinger/dmg-sim` @ `786f8c8aaac7`, CC-BY-SA-4.0):
SystemVerilog generated from `msinger/dmg-schematics` netlists of a DMG-CPU B
die, including the SM83 and its decoders; a different person's tracing, so
independent of Gekkio's. Simulates the whole console with Icarus Verilog
(`dmg_cpu_b_gameboy.vvp` builds in seconds here); its `tests/` hold expected
screen/save results for blargg and Mooneye with listed expected failures
(`oam_bug` 2, 4, 5, 7, 8; `dmg_sound` 10). Speed measured here: about 0.1
simulated seconds per 4–5 minutes wall. Run here: Mooneye `instr/daa` (the
ROM in dmg-sim's own `tests/roms`, an older build) with `quickboot.bin`, 0.6
simulated seconds, **3,044 s wall, frame 36 byte-identical to dmg-sim's
expected `result.png`: pass**. A judge for short programs and bus-level
questions (FST dumps), not for corpora.

**GateBoy** (`aappleby/metroboy` @ `36797ad4cf77`): gate-level for the rest of
the DMG, but its CPU is "my current best guess", not traced (C6). Never a CPU
judge.

### Emulator-derived detectors

- **SameBoy** (`LIJI32/SameBoy` @ `c458e7c5d2d3`, Expat): the most explicit
  emulator source for HALT, STOP, dispatch sampling and the OAM bug.
  `make tester` builds `sameboy_tester` (2 s here, with rgbds 1.0.4 from the
  pinned bundle); `sameboy_tester --dmg --length 60 ROM...` writes a `.bmp`
  screenshot next to each ROM. Run here: `cpu_instrs` "Passed all tests",
  `instr_timing` Passed, `halt_bug` Passed, Mooneye `daa`, `ie_push`,
  `ei_sequence`, `halt_ime0_ei` Test OK. Its `BootROMs/` build free DMG/CGB/SGB
  boot ROMs, used as MAME's substitute.
- **MAME 0.285**: see [mame-oracle.md](mame-oracle.md); fails `halt_bug`,
  `ei_sequence`, `ie_push`.
- **gbit** (`koenk/gbit` @ `9b5c5afd281e`, MIT): instruction-by-instruction
  differential tester against the author's emulator; has a Python wrapper. A
  convenience, below SingleStepTests in coverage.
- Opcode tables: `gbdev/gb-opcodes` @ `376f61c86fda` (CC0, `Opcodes.json`),
  `izik1/gbops` @ `90b9bf296aed` (MIT, `dmgops.json` with per-M-cycle access
  types).

### Not available

- No Sharp datasheet with an opcode table (the 1990/1996 data books describe
  SM83 at a high level, GBCTR §History) and no hardware-captured per-instruction
  corpus. The SM83's semantics rest on blargg/Mooneye/Gambatte plus the die
  models; its internal-cycle addresses on GBCTR plus the die models.
- No Nintendo boot ROM is fetched or needed: SameBoy's and dmg-sim's free boot
  ROMs both hand over the DMG register values (mame-oracle.md). Real ones
  (hashes in gameboy-python's `docs/start-here.md` "Boot ROMs") are optional for
  rung 4 and never committed.

## The plan, in oracle-tier order

Each rung is cheaper than the next and earns one claim. Do not reorder.

| Rung | Gate | Tier | Claim earned |
| --- | --- | --- | --- |
| 0 | Generated opcode table == `gb-opcodes` mnemonics/lengths and GBCTR categories; for every opcode and path, the core's (kind, address, idu) per M-cycle == `tests/gbctr_timing.json` on random states; readability test | research documentation | the bus schedule is GBCTR's, internal cycles included |
| 1 | SingleStepTests sm83: 498 files × 1,000 (no `76`, `10`), registers + `ime`/`ei` + RAM + every read/write (address, data, order) + kind of every cycle; adtennant v2 registers | emulator-derived (detector, high volume) | agreement with Ares/JSMoo everywhere except internal addresses, where GBCTR rules |
| 2 | blargg `cpu_instrs` 01, 03–11 in `sm83_python.harness`: serial text ends "Passed", CPython and PyPy, wall time recorded | hardware-verified | instruction semantics as blargg's hardware CRCs see them |
| 3 | Mooneye in the harness: `daa`, `reg_f`, `ie_push`; then `if_ie_registers`, `ei_sequence`, `ei_timing`, `rapid_di_ei`, `intr_timing`, `reti_intr_timing` once the harness completes serial transfers (SC bit 7 clears after a write of $81) instead of the mock SoC's constant $7F | hardware-verified | DAA on every input, F's low nibble, IE-push cancellation, EI/DI sequences |
| 4 | MAME replay with I/O reads fed from MAME's log (mame-oracle.md) on several commercial-style programs; per-instruction registers and cycle deltas | emulator-derived | long real-code agreement; every divergence explained by a higher tier |
| 5 (after 0–3; not blocking them) | Gekkio's VHDL: rung 2/3 ROMs agree; new per-instruction testbench dumps die-derived bus cycles incl. internal addresses for all opcodes and dispatch; compare with the core. Spot-check on dmg-sim | die-traced | internal-cycle addresses and dispatch bus from the die, not from one document |
| 6 | Through gameboy-python: blargg 02, `instr_timing`, `mem_timing`, `mem_timing-2`, `halt_bug`, `oam_bug`; Mooneye timing tests; Gambatte `halt`, `irq_precedence`, `undef_ops`, `speedchange`; SameSuite `ei_delay_halt` | hardware-verified / hardware-captured | HALT, wake-up, dispatch timing and STOP as the hardware does them, on DMG then CGB |

Rung 6 is the board's acceptance, not this repository's; failures it traces
to the core come back here as issues or PRs with a failing core-level test.

## Results (2026-10-07)

Run on this machine against the core as built (CPython 3.14 and PyPy 3.11, both green).

Rerun 2026-11-12 at 95f2b8b (after the `halt_sees` and `late` flags) on PyPy 3.11: the quick
suite (1,478 tests) and the whole slow suite (506 tests: all 498 SingleStepTests files, blargg,
Mooneye, the MAME replay of blargg `06`, both die models end to end; 30 minutes) pass, and 15 of
the 75 Mooneye acceptance ROMs pass in the harness. The six commercial games of rung 4 were not
replayed again (their traces and ROMs are local, not fetched).

| Rung | Result | Tier of the claim |
| --- | --- | --- |
| 0 | Generated opcode table = GBCTR's `opcodes.toml` mnemonics and categories = `gb-opcodes` lengths (cross-checked by `scripts/gen_opcode_table.py`); for all 514 opcode paths the core's (kind, address, IDU direction) per M-cycle equals GBCTR's evaluated on random states (mutation-checked); readability test (one mnemonic family per handler, a source on every headline, module ownership) | research documentation |
| 1 | SingleStepTests sm83: **498 files, 498,000 cases** pass (reads, writes, data, order; internal cycles by kind; `ime`, `ei`); adtennant v2: 241 files pass (registers and RAM). `$FFFF` cases need `ie` seeded from the corpus's RAM because the core owns `$FFFF` | emulator-derived (detector) |
| 2 | blargg `cpu_instrs` 01, 03-11: `Passed` (0.1-4.7 s each on CPython); 02 prints `Timer doesn't work` / `Failed #4` as documented (the harness has no TIMA) | hardware-verified |
| 3 | Mooneye: `instr/daa`, `bits/reg_f`, `interrupts/ie_push`, `if_ie_registers`, `ei_sequence`, `ei_timing`, `rapid_di_ei`, `intr_timing`, `reti_intr_timing` pass (the harness completes serial transfers and counts DIV); `div_timing` and `pop_timing` also pass. Of the 75 acceptance ROMs, 15 pass board-free; the rest need TIMA, the PPU or OAM DMA | hardware-verified |
| 4 | MAME replay (`scripts/mame_trace.py --io`, `sm83_python.replay`): **no divergence** in PC, A, F, B, C, D, E, H, L, SP, IE, I/O read order or non-HALT cycle counts over blargg `03` (0.73 M instructions) and six commercial games (Kirby's Dream Land 2.62 M, Metroid II 1.11 M, Castlevania 0.74 M, Bubble Bobble 0.56 M, Dr. Mario 0.54 M, Super Mario Land 0.24 M; about 2,900 HALT wake-ups and 544 interrupts MAME took outside HALT). Mutation-checked. MAME bills one cycle less to the first instruction after a HALT wake-up; a trace cannot place it, so that one group is not cycle-checked | emulator-derived (detector) |
| 5 | Gekkio's VHDL SM83 and msinger's dmg-sim each agree with the core on **all 533 cases / 11,316 M-cycles** of the all-opcodes ROM (kind, address and data of every cycle, internal cycles included); 15 HALT-entry scenarios on the VHDL model; 24 timer-woken HALT scenarios on dmg-sim (2-15 halted cycles, IME on and off). The comparison changed the core in five places (below) | die-traced (two independent tracings) |

What rung 5 changed (each a deviation from this document's earlier text, now corrected in
[timing.md](timing.md) and [undocumented-behavior.md](undocumented-behavior.md)):

1. `JR`'s internal cycle drives `{PCH, $00}`, not PC (GBCTR's "PCH" is literal).
2. A locked CPU drives `$0000` on every cycle.
3. A halted CPU drives `$0000` on every cycle (not PC), and resumes in the cycle after IF rises.
4. HALT that halts takes two cycles (fetch, then a read of the next byte without moving PC); the
   HALT bug takes one; the decision uses the interrupt state sampled before HALT's own fetch.
5. `EI; HALT` with an interrupt pending: HALT's cycle is the dispatch's discarded fetch.

Limits of the die checks: the VHDL model on Gekkio's mock SoC never wakes a halted CPU (the
interrupt latch that does it is clocked by a clock the mock gates), so wake-up rests on dmg-sim;
STOP is not tested on either (no joypad or KEY1 in the mock; dmg-sim could, not done); the
mock SoC's `reti_intr_timing` failure noted above is unexplained and not the core's.
