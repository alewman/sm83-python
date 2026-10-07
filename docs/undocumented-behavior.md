# Undocumented behaviour, quirks, and contradictions

Nintendo's programming manual and Sharp's data books are not public sources
here (Sharp's 1996 *Microcomputer Data Book* describes the SM83 but has no
opcode table and "some mistakes in the descriptions", GBCTR §History). Every
rule below therefore rests on test ROMs run on hardware, die-traced models,
or emulator authors' research; each item names which. Tier words are defined in
[validation.md](validation.md).

## Behaviour items (U)

**U1. F bits 3–0 are always 0.** `POP AF` and anything else that would load F
keep only bits 7–4. *Hardware:* Mooneye `bits/reg_f` (DMG … AGS). The corpus
never starts with low bits set (0 of 500,000 initial states), so it cannot
catch a core that keeps them; `POP AF` (`f1.json`) does load them from RAM, so
check that file's final F.

**U2. DAA.** Uses N, H, C only. After an addition (N = 0): add $06 if H or the
low nibble > 9; add $60 if C or A > $99, and set C. After a subtraction (N = 1):
subtract $06 if H; subtract $60 if C (C stays set). Z from the result, H ← 0, N
kept. *Hardware:* Mooneye `instr/daa`, every input combination, verified on
every model, board-free, also passed by Gekkio's die-traced VHDL (run here
2026-10-05, 100 s). *Emulator:* SameBoy `daa()`. GBCTR's DAA section is TODO.

**U3. The 11 holes lock the CPU.** `$D3 $DB $DD $E3 $E4 $EB $EC $ED $F4 $FC
$FD`: no further fetch, interrupts are never serviced. *Hardware-captured:*
Gambatte `hwtests/undef_ops/undef_op_XX_dmg08_cgb04c_out01` (all eleven minus
`$DD`, which has no test; IE = VBlank enabled, IME = 1: the handler that would
print 03 never runs; DMG and CGB). *Explanation:* SonoSooS "Opcode holes"
(the decode ROM yields no fetch). SameBoy models it as "halt with IE = 0",
which has the same visible effect. Implement as a `locked` state the host can
query; do not raise. **Bus (rung 5, both die models):** after the locking fetch every M-cycle
is idle with the address bus at `$0000`.

**U4. HALT bug.** HALT with IME = 0 and `IE & IF & $1F` ≠ 0 (sampled before the HALT's own
fetch) does not halt and inhibits the PC increment of the next fetch: the following byte is
fetched twice; `RST` after it pushes its own address; a second `HALT` after it spins
forever re-reading itself. **Bus (rung 5, VHDL die):** HALT makes no cycle of its own then; the
following byte is simply fetched at PC, again at PC, then PC + 1, so a 1-cycle instruction
there runs twice. *Hardware:* blargg `halt_bug.gb` (needs a timer:
board), nitro2k01 `double-halt-cancel` (README describes the hardware result).
*Emulator:* SameBoy `halt()` (sets `halt_bug`, consumed at the next fetch).
SameBoy says it also happens on CGB in both modes.

**U5. `EI; HALT` with an interrupt pending.** The interrupt is serviced, and
the handler returns to the HALT, which executes again (the PC-increment
inhibition meets the dispatch's PC decrement). **Bus (rung 5, VHDL die):** HALT's cycle is the
dispatch's discarded fetch (at the next byte, PC not advanced), then PC goes back onto the
HALT and the usual internal cycles and pushes follow; the core carries this as `halt_dispatch`. *Hardware:* SameSuite
`interrupt/ei_delay_halt.asm`, cited by Pan Docs `halt.md`. If HALT is also
followed by `RST`, the EI case wins (Pan Docs).

**U6. HALT with IME = 1 and an interrupt already pending.** No halt; the
dispatch happens at the HALT and returns to it (SameBoy `pc--`; SonoSooS table
"Jump to vector on fetch of HALT opcode"). Mooneye `halt_ime1_timing`.

**U7. HALT wake-up timing differs DMG vs CGB** (and the DMG wake itself is settled, see
[timing.md](timing.md) "HALT": the CPU resumes in the cycle after IF rises, dmg-sim, 24 cases). SameBoy adds 2 T-cycles on
leaving HALT on DMG only; Mooneye `halt_ime1_timing2-GS` and `di_timing-GS`
pass on DMG/MGB/SGB/SGB2 and fail on CGB/AGB/AGS. Sub-M-cycle: the board's,
but the core must report each halted M-cycle so the board can place it.

**U8. IE written by the dispatch push.** See [timing.md](timing.md)
"Interrupt dispatch": IE sampled after the high-byte push, IF after the low
one; nothing left → PC = $0000, IF untouched, IME = 0. *Hardware:* Mooneye
`interrupts/ie_push` (all models). *Explanation:* SonoSooS ("PC is only written
in M3"). **MAME 0.285 fails this test** ("R1: not cancelled", run here).

**U9. EI delay and DI.** EI enables after the next instruction; DI cancels a
pending EI; RETI enables at once. *Hardware:* Mooneye `ei_sequence`,
`ei_timing`, `rapid_di_ei`, `reti_intr_timing`. **MAME 0.285 fails
`ei_sequence`** ("FAIL: NO INTR").

**U10. CB-prefixed instructions are not interruptible between the prefix and
the opcode.** SonoSooS "$CB prefix". Follows from the fetch model; no test
isolates it.

**U11. STOP.** One byte that may appear as two; outcome depends on joypad
lines, pending interrupts, IME, and on CGB KEY1. SonoSooS table (IME = 0);
SameBoy `stop()`; LIJI's flowchart in Pan Docs. Includes a "zombie mode" and a
glitched interrupt to $0000 when the joypad interrupt fires during wake-up
(SonoSooS). Unverified on DMG by any test pinned here; CGB speed switching is
covered by Gambatte `speedchange` (hardware-captured).

**U12. IDU addresses on internal cycles.** See [start-here.md](start-here.md)
"The bus". *Sources:* GBCTR's tables (single author, Gekkio, who also wrote
the VHDL model: not independent), Pan Docs `OAM_Corruption_Bug.md` (which
counts `POP` as triggering the bug 3 times and `PUSH` 4 times), blargg
`oam_bug` (hardware-verified, DMG, board). **Settled 2026-10-07 (rung 5):** both die-traced
models, Gekkio's VHDL and msinger's independently traced dmg-sim, give the same internal-cycle
addresses as GBCTR's tables for all 505 opcodes (both paths), all 256 CB opcodes and the
interrupt dispatch, with one correction: `JR`'s internal cycle drives `{PCH, $00}`, not PC.
The OAM-bug corruption pattern itself is the board's (rung 6, `oam_bug`).

**U13. A possible NMI.** SonoSooS lists "NMI (0x80)" and a "bugged interrupt
(0x00)" in the dispatch priority. No Game Boy model wires an NMI; nothing here
tests it. Do not implement; record if the die models show it.

**U14. Interrupt dispatch from HALT on wake costs a discarded fetch.** SonoSooS
HALT table ("wakeup from HALT mode, dummy fetch (with increment)"). Mooneye
`halt_ime1_timing` measures it on a board. **dmg-sim (rung 5):** there is no cycle of its own:
the cycle after IF rises *is* the dispatch's discarded fetch (IME = 1) or the refetch of the byte
after the HALT (IME = 0).

## Contradictions between sources (C)

**C1. Internal-cycle addresses: SingleStepTests vs GBCTR.** The corpus writes
the previous cycle's address on `---` cycles ("For convenience, we often just
use the last address generated", its README); GBCTR writes the IDU register or
$0000 (e.g. `INC BC` M2: corpus PC, GBCTR BC). *Rule:* compare reads and writes
(address, data, order) against the corpus; ignore its address on internal
cycles; take internal addresses from GBCTR. **Confirmed by both die models** (rung 5), except
that GBCTR's "PCH" on `JR` means `{PCH, $00}`.

**C2. Pan Docs' "two wait states" vs SonoSooS' IDU cycles in dispatch.**
Pan Docs `Interrupts.md` describes the first two dispatch M-cycles as "nothing
happens; presumably nops"; SonoSooS and SameBoy put a discarded fetch and two
IDU operations there, with addresses on the bus. Both count 5. *Rule:* SonoSooS/
SameBoy (they name the bus activity, and the OAM bug depends on it).

**C3. HALT and STOP in the corpus.** SingleStepTests records `$76` and `$10` as
three M-cycles with PC + 1 and no halting; adtennant's v2 corpus omits them
("not meaningful"). Neither is a hardware statement. *Rule:* exclude `76.json`
and `10.json` from the corpus gate; judge HALT with Mooneye, blargg, Gambatte;
STOP with Gambatte `speedchange` and SameBoy.

**C4. `EI` final state in the corpus.** SingleStepTests' `fb.json` final state
has `"ei": 1` and `ime` 0; its initial states carry `ie` and `ime` that its README
says to "ignore ... for now". *Rule:* compare `ime` and `ei` in final states;
ignore `ie`.

**C5. GBCTR's `mem_rw` labels.** In `LD (nn),SP` the label row says SPH then SPL
while the data row and the pseudocode write SPL to nn and SPH to nn + 1; and the
row as a whole is offset one cycle early. *Rule:* the data row and pseudocode
(`scripts/gbctr_timing.py` derives `kind` from the data row). Report upstream.

**C6. GateBoy's CPU is not die-derived.** Easy to assume from "gate-level
simulation of the original Game Boy"; its README says the CPU is "my current
best guess". *Rule:* GateBoy is never a judge for the SM83. The die-traced SM83
models are Gekkio's VHDL (`gb-research/sm83-cpu-core/hdl`) and msinger's
netlist in dmg-sim.

**C7. MAME as a referee.** MAME 0.285 passes cpu_instrs, instr_timing,
mem_timing, daa, di_timing-GS, halt_ime0_ei, intr_timing, push_timing,
rapid_di_ei, and fails halt_bug, ei_sequence, ie_push (run here 2026-10-05,
[mame-oracle.md](mame-oracle.md)). *Rule:* MAME is a detector for ordinary code
only; never for HALT, EI, or dispatch corners.

## Open items

- STOP on DMG: no test pinned here exercises stop mode; MAME and SameBoy are the only
  references. The core implements the board hook and the decode; the outcome is the board's.
- The DMG/CGB difference in leaving HALT (U7) and the OAM bug's effect (U12) are judged on the
  board, rung 6.
- Whether the corpus's `ime`/`ei` semantics match the core's EI model on the case where EI is
  followed by an interrupt check (C4): the core passes all 498,000 cases comparing `ime` and `ei`
  in final states, and Mooneye `ei_sequence`, `ei_timing`, `rapid_di_ei` (hardware-verified).
