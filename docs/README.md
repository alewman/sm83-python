# Documents

Read in this order.

| Document | What it holds |
| --- | --- |
| [start-here.md](start-here.md) | The SM83 vs the LR35902; registers and flags; the instruction set and its machine-readable sources; M-cycles; fetch/execute overlap; the bus with internal cycles; interrupts, HALT, STOP, reset; what the core does not own |
| [timing.md](timing.md) | Agreement measured between GBCTR and SingleStepTests; every instruction category's M-cycles with addresses; interrupt dispatch row by row with the IE/IF sampling points; EI/DI/RETI; HALT; STOP; double speed |
| [undocumented-behavior.md](undocumented-behavior.md) | Items U1–U14 (F's low nibble, DAA, the holes, the HALT bug, EI+HALT, IE push, STOP, IDU addresses, ...), contradictions C1–C7 between sources, open items |
| [validation.md](validation.md) | Every oracle by tier with pins; what was run here and what it showed; the die-traced models; the rung plan |
| [mame-oracle.md](mame-oracle.md) | The verified MAME 0.285 recipe with a free boot ROM, its trace format, and how MAME scores on the CPU tests |
| [handoff-brief.md](handoff-brief.md) | The task for the session that builds the core: decisions, the bus contract, the harness, rungs, tooling, open decisions |

## Findings made while gathering (2026-10-05)

These came from running things, not from any single document:

1. **GateBoy is not a CPU judge.** Its README says its CPU is "my current best
   guess", not traced from the die. Two die-traced SM83 models do exist and run
   here without sudo: **Gekkio's VHDL** (`gb-research/sm83-cpu-core/hdl`, GHDL)
   passed Mooneye `daa`, `reg_f`, `ie_push` and blargg `01-special` on its mock
   SoC but **fails `reti_intr_timing`**, which hardware passes (so it judges only
   where it agrees with hardware tests), and dumps its decoder in 9 s; **msinger's dmg-sim** (the whole DMG-CPU B, SM83 included,
   Icarus Verilog) builds in seconds, simulates about 0.1 s of console time
   per 4–5 minutes, and passed Mooneye `daa` in 51 minutes.
2. **SingleStepTests sm83 and GBCTR agree** on the M-cycle count of 498 of 500
   opcodes on every case, and on the read/write/internal sequence of all
   498,000 cases; they disagree only on what address an internal cycle shows
   (the corpus repeats the last address "for convenience"). That disagreement is
   exactly what the OAM bug depends on, so the bus contract carries the IDU
   address and rung 5 settles it from the die.
3. **MAME 0.285 fails three hardware-verified CPU tests**: blargg `halt_bug`,
   Mooneye `ei_sequence` and `ie_push`. It passes `cpu_instrs`, `instr_timing`,
   `mem_timing`, `daa` and the others tried. Detector for ordinary code only.
4. **No Nintendo boot ROM is needed anywhere.** MAME runs with SameBoy's or
   dmg-sim's free boot ROM after a checksum warning, and both hand over the DMG
   register values.
5. **The upstream Gambatte repository has gone private**; its hardware-captured
   test suite survives in `pokemon-speedrunning/gambatte-core` and is pinned
   from there.
6. **GBCTR's `mem_rw` row is a diagram label**, one cycle early and once with
   SPH/SPL swapped; the data row and pseudocode are consistent, so the
   extractor reads those.
