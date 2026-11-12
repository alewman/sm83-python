# Handoff: build `sm83-python`, the Game Boy's CPU core

> **Historical: the brief this core was built from, 2026-10-05.** Current state: the
> [README](../README.md) and [validation.md](validation.md). The decisions and the bus contract
> below are still the core's (the code cites them); [build-log.md](build-log.md) lists where the
> oracles overruled the rest (HALT, halted and locked bus cycles, `JR`), and
> [timing.md](timing.md) has the two `request_interrupt` flags added later (`halt_sees`,
> `late`, 2026-11-08). Paths such as `/data/emu/...` are the machine it was written on.

## Context you are inheriting

The family's shape is **chips are cores, boards compose cores**. Each core is
certified on its own against its oracles and pinned by the boards that use it.
This core's first user is `gameboy-python` (`/data/emu/gameboy-python`, being
prepared in parallel), later CGB/SGB modes of the same board and, one day, a
GBA board's backward-compatible mode. A board that finds a corner of this core
raises it **on the core** (an issue or a PR here, re-certification is fine),
never as a workaround in the board.

Models for the code and the tooling:

- `z80-python` (`/data/emu/z80-python`, v0.4.0 on PyPI): the readability
  contract (one instruction family per module, one mnemonic per handler
  docstring, the hardware reason as a comment on the line that encodes it),
  the tooling bar (`state.py`, `disasm.py`, `debug.py`, `trace.py`,
  `console.py`, `python -m`), `docs/` layout, oracle tiers.
- `6502-python` (`/data/emu/6502-python`, 0.2.0): **every CPU cycle is one bus
  callback, in chip order**. That is the property this core needs too, plus
  the internal cycles the 6502 does not have.
- `m6800-python` (`/data/emu/m6800-python`): the rung ladder, a generated
  opcode map, scripts that drive MAME and second emulators.

The user's rules that bind this work:

- **Oracle tiers**: hardware-captured > hardware-corrected > emulator-derived
  (die-traced models sit beside hardware-corrected; see validation.md); a
  low-tier oracle is a detector, never a judge; state the tier of every claim.
- **Python floor 3.11** (the newest PyPy supports): `requires-python = ">=3.11"`,
  ruff `target-version = "py311"`, CPython and PyPy both green.
- **Reference cores are correct, not fast.** A `-fast` fork is later work.
- **Modern over compat**: callables, dataclasses, no shims; there are no
  external users yet.
- **No dangerous-looking shell one-liners** in scripts or docs (no `rm -rf`,
  `sed -i`); keep CI minimal (PyPy only, main + PRs, cancel in progress) if and
  when a GitHub repo exists. This repository is **local git only** until
  rung 3 passes (see "Decided by the user").

### Read, in this order, before writing code

1. `README.md`.
2. `docs/start-here.md`: registers, the instruction set, fetch/execute
   overlap, the bus as the SoC sees it, interrupts, HALT, STOP, what the core
   does not own.
3. `docs/timing.md`: every category's M-cycles with addresses; dispatch;
   EI/DI/RETI; HALT; STOP.
4. `docs/undocumented-behavior.md`: items U1–U14, contradictions C1–C7.
5. `docs/validation.md`: every oracle with tier and pin; the measured results;
   the rungs.
6. `docs/mame-oracle.md`.
7. `/data/emu/z80-python/docs/start-here.md` ("The embedding contract") and
   `src/z80_python/`; `/data/emu/6502-python/src/sixfiveohtwo/cpu.py`.

Then `python scripts/fetch_references.py` (16 repositories, 5 files incl. a
750 MB simulator bundle; `--no-tools` skips it) and
`python scripts/build_referees.py` (SameBoy tester + free boot ROMs, GHDL venv
for Gekkio's die model, dmg-sim). `python scripts/gbctr_timing.py` writes
`tests/gbctr_timing.json`.

## Decisions already made

- **Name `sm83-python`**, import package `sm83_python`, class `SM83`. SM83 is
  the CPU; LR35902 is the DMG system-on-a-chip.
- **The core is one class for every model.** DMG, MGB, SGB, CGB and AGB share
  the SM83; the documented differences between them (HALT wake-up by 2
  T-cycles, OAM bug, double speed, STOP outcomes) are sub-M-cycle or SoC
  behaviour and belong to the board, which the core must give enough
  information to model.
- **Fetch-first `step()`** (model (a) in start-here.md): a step starts with the
  opcode fetch and ends after the instruction's last execute cycle, so the
  next fetch belongs to the next step. Reason: SingleStepTests sm83 records
  cycles this way (first entry = fetch at PC), so its 498,000 usable cases
  compare cycle for cycle; GBCTR's overlapped tables convert by moving the final
  fetch to the front of the next instruction (start-here.md shows the two are
  the same bus sequence).
- **IE and IF are core attributes** `ie` and `if_` (decided by the user,
  2026-10-05). GBCTR puts IE in the core; IF is SoC-side on the die, but the
  core samples it at exact cycles of the dispatch (timing.md) and an attribute
  read is exact and cheap. Rules:
  - **The core owns $FFFF.** A write to $FFFF updates `cpu.ie` inside the core
    *before* the write callback returns control to the instruction, and a read
    of $FFFF returns `cpu.ie` (all 8 bits as written: SameBoy stores the full
    byte; not verified on hardware here, a board-level Mooneye/Gambatte check). The callback is
    still made (the cycle exists; watchpoints see it); the board must not map
    $FFFF itself. This is what makes Mooneye `ie_push` work in-core: the
    dispatch's high-byte push to $FFFF changes `ie` before the core samples it.
  - **The board raises interrupts with `cpu.request_interrupt(bit)`**
    (bit 0 VBlank … 4 Joypad), which sets `if_ |= 1 << bit`. It may be called
    from inside any bus callback. *Same-cycle visibility:* a request made
    during M-cycle k's callback is visible to every core decision taken after
    that callback returns: the pending check at the start of the next `step()`,
    HALT wake-up on the next halted cycle, and the dispatch's IF sample after
    its low-byte push (so a request during that push's callback can still pick
    the vector). It is never visible to a decision already taken earlier in the
    same `step()`.
  - **$FF0F stays on the board's map** (it is SoC I/O): the board's read of
    $FF0F returns `cpu.if_ | 0xE0` and its write sets `cpu.if_ = value & 0x1F`
    (Mooneye `if_ie_registers`: upper bits read 1). The dispatch clears the
    serviced bit itself.

## The bus contract (required)

One callback per M-cycle, in chip order, **including internal cycles**, each
with the address the CPU drives:

```python
cpu = SM83(read_byte, write_byte, idle)
#   read_byte(address) -> int      one M-cycle that reads
#   write_byte(address, value)     one M-cycle that writes
#   idle(address)                  one M-cycle with no access; address is the
#                                  IDU's register or $0000 per GBCTR
# cpu.idu is +1, -1 or 0 before each callback: what the IDU did to the value
# on the address bus this cycle (fetch: +1; LD A,(HL-): -1; ADD HL,BC M2: 0).
# cpu.halted / cpu.stopped / cpu.locked are readable inside callbacks.
# cpu.request_interrupt(bit) may be called inside callbacks (see Decisions).
cycles = cpu.step()   # M-cycles consumed == number of callbacks made
```

- `idle` defaults to a no-op; a host that ignores internal cycles still gets
  correct instruction timing from the return value. The board needs it for the
  OAM corruption bug (start-here.md "The bus") and blargg `oam_bug`.
- The board advances its devices **inside** the callbacks (4 T-cycles per
  call, 2 in CGB double speed), never by adding `step()`'s return value on top.
- The return value equals the number of callbacks. Assert it in tests.
- A halted or locked CPU makes `step()` perform exactly one idle cycle and return 1; the board
  loops. (Built: the address is **`$0000`**, not PC, in both states, as both die models drive it;
  see timing.md "HALT".) HALT wake-up and dispatch follow timing.md.
- **STOP hook**: `SM83(..., stop=callable)`. On `$10` the core calls
  `stop(pending)` (pending = `ie & if_ & 0x1F != 0`) and the board returns
  what happens: enter stop mode, behave as HALT, behave as a 1-byte NOP, or
  switch speed, each with whether the second byte is consumed (timing.md
  "STOP", SameBoy `stop()`). Default when no hook is given: a 2-byte STOP that
  enters `stopped` until `if_` changes, enough for the harness.
- Keep the contract transcribable: plain integers, no generators or
  coroutines in the hot path, so `sm83-rust` and `-fast` forks can copy it.

## Your task

Build `src/sm83_python/` to the contract above and pass the rungs in
[validation.md](validation.md) "The plan", in order. Each rung's acceptance is
there. In summary:

0. **Tables.** Generate the opcode map (mnemonic, length, category) from
   `gb-opcodes/Opcodes.json`, checked against GBCTR's `opcodes.toml`
   categories; hand-write the handlers. A per-category bus-schedule test from
   `tests/gbctr_timing.json`: for every opcode and both paths, the sequence of
   (kind, address, idu) the core produces equals GBCTR's, with symbolic
   addresses evaluated on a random state. Readability test (one mnemonic per
   handler docstring), as z80-python has.
1. **SingleStepTests sm83**, 498 files × 1,000 cases (exclude `76`, `10`):
   registers, `ime`, `ei`, RAM, and every read/write cycle's address, data and
   kind; internal cycles compared by kind only (C1). adtennant v2 as a second
   detector.
2. **blargg `cpu_instrs`** 01 and 03–11 in the minimal harness
   (`sm83_python.harness`, below): serial output ends in `Passed`.
3. **Mooneye board-free subset** in the harness (list in validation.md):
   B/C/D/E/H/L = 3/5/8/13/21/34 at `LD B,B`.
4. **MAME replay** of real code with I/O reads fed from MAME's log
   (mame-oracle.md "Use"): detector.
5. **Die cross-check**: run the rung 2/3 ROMs on Gekkio's VHDL SM83 (already
   works, ~6,400 instructions/s) and write a VUnit testbench that drives it
   from SingleStepTests-style initial states to dump die-derived per-cycle bus
   activity *including internal-cycle addresses*; settle C1/U12. Confirm on
   dmg-sim (msinger's independent netlist).
6. **Through the board**: gameboy-python's milestone that runs blargg
   02-interrupts, `instr_timing`, `mem_timing`(-2), `halt_bug`, `oam_bug` and
   Mooneye's timing tests certifies the parts of this core only a board can
   exercise. Its failures that are the core's come back here as issues/PRs.

### The minimal harness (`sm83_python.harness`)

A host that is not a Game Boy, for rungs 2–4 and the CLI. Model it on Gekkio's
mock SoC (`gb-research/sm83-cpu-core/hdl/simulation/test_soc.vhd` and
`test_rom_tb.vhd`), which runs the same ROMs on the die model: ROM at
$0000–$7FFF with a bank register written at $2000–$2FFF (MBC1-style, enough
for 64 KiB `cpu_instrs.gb`), RAM elsewhere, `LY` ($FF44) reads $90, `SC`
($FF02) reads $7F (serial always done), writes to `SB` ($FF01) collected as
text (Mooneye's ROMs that rely on the serial *interrupt* hung on exactly this
mock SoC: validation.md; give the harness a serial port that completes a write
of $81 to SC after 8 bits and raises IF bit 3, and check those ROMs then pass), $FF0F/$FFFF mapped to the core's `if_`/`ie`, and a stop condition on an
infinite `JR` to itself or `LD B,B`. Start at $0100 with the DMG post-boot
registers (Pan Docs `Power_Up_Sequence.md`), or at $0000 with SameBoy's free
boot ROM. No timer, no PPU: tests that need them belong to rung 6.

### Tooling at the family bar

`state.py` (`CPUState` with `ime`, `ei_pending`, `halted`, `halt_bug`,
`stopped`, `locked`, `ie`, `if_`, `wz` if you keep it), `disasm.py` (sharing the
generated table; check against MAME's disassembly of the same trace),
`debug.py` (`DebugSession` with breakpoints, bus watchpoints that see internal
cycles too), `trace.py` (JSONL, the family schema with `kind` = read, write,
internal and the `idu` value), `console.py`, `py.typed`, and
`python -m sm83_python ROM.gb [--boot BOOT] [--max-cycles N] [--trace out.jsonl]`
running a ROM in the harness and printing the serial text.

## Decided by the user (2026-10-05)

1. IE and IF are core attributes; the board raises IF bits through
   `request_interrupt(bit)` with the visibility rule above; the IE write during
   the dispatch push is handled in-core (the core owns $FFFF).
2. **Local git only until rung 3 passes**; then a **private** GitHub repo
   `alewman/sm83-python`. CI then follows the family's minimal-minutes rule:
   one interpreter (PyPy), on `push` to `main` and on `pull_request`,
   `concurrency` with cancel-in-progress, a job timeout; heavier oracle runs
   only on `workflow_dispatch`.
3. **Rung 5's per-instruction die testbench is in the first build session**,
   after rungs 0–3 pass; it does not block them. Rung 4 (MAME replay) may run
   before or after it.

## Boot ROMs

Never committed, never needed by rungs 0–3 (the harness starts at $0100 with
the DMG post-boot registers). Real Nintendo boot ROMs exist locally, listed
with paths and hashes in `/data/emu/gameboy-python/docs/start-here.md`
"Boot ROMs" (DMG Rev 1 = MAME `dmg_boot.bin`, SHA-1 `4ed31ec6…`). For rung 4
they are optional: copied into MAME's per-run `roms/gameboy/` (gitignored
`tests/mame_traces/`), they remove the checksum warning and give real boot
timing; SameBoy's free ROM remains the default of `scripts/mame_trace.py`.
