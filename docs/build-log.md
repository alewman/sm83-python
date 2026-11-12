# Build log: the core, 2026-10-07

> **Historical: the record of the first build, 2026-10-07.** Current state: the
> [README](../README.md) and [validation.md](validation.md). Since then: the GitHub repository and
> CI (PyPy, `pytest -m "not slow"`, ruff), and `request_interrupt`'s `halt_sees` and `late` flags
> (2026-11-08, from the board's rung 6 work; [timing.md](timing.md)).

What was built against [handoff-brief.md](handoff-brief.md), what the oracles changed, and what
is left. The brief is the task as given; this is the record of the result.

## Built

`src/sm83_python/`, pure Python, no dependencies, `requires-python >= 3.11`, CPython and PyPy:

| Module | What |
| --- | --- |
| `cpu.py` | `SM83(read_byte, write_byte, idle=None, stop=None)`; `step()`, `request_interrupt(bit)`, `reset()`, `capture_state()` / `restore_state()` |
| `_core.py` | registers, the bus helpers (one callback per M-cycle, `cpu.idu` set before each), `step()`, interrupt dispatch, the halted / stopped / locked cycles |
| `_loads.py`, `_alu.py`, `_rotate.py`, `_control.py` | the instruction families; each handler's docstring starts with its mnemonics and ends with its source |
| `_dispatch.py`, `_opcodes.py` | the decode table (bit patterns, first match wins); the generated mnemonic / length / category table |
| `state.py`, `stop.py` | `CPUState` (frozen, validated), `StopResult` / `StopAction` for the STOP hook |
| `disasm.py`, `debug.py`, `trace.py`, `console.py`, `__main__.py` | the family tooling; [trace-schema.md](trace-schema.md) |
| `harness.py` | the minimal host: ROM with an MBC1-style bank register, RAM, `LY = $90`, a serial port that completes and interrupts, DIV, `IF`/`IE` on the core |
| `replay.py` | MAME replay (rung 4) |

Scripts: `gen_opcode_table.py`, `mame_trace.py --io`, `die_programs.py`, `die_run.py`/`die_sim.py`
(Gekkio's VHDL, with `scripts/die/bus_dump_tb.vhd` and `test_soc_irq.vhd`), `die_compare.py`,
`die_halt.py`, `dmgsim_run.py`/`dmgsim_rows.py`/`dmgsim_halt.py` (msinger's dmg-sim, with
`scripts/dmgsim/bus_probe.sv`). Nothing under `reference/` is modified.

## Running the gates

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -m "not slow"        # rungs 0, 1 (sample), harness, tooling: seconds
.venv/bin/python -m pytest                      # + the full 498,000 cases, blargg, Mooneye, MAME, both die models
.venv/bin/python -m sm83_python ROM.gb          # run a ROM in the harness
```

Rung 4 and 5 need MAME and the simulators (`scripts/build_referees.py`); those tests skip without them.
The suite passes on CPython 3.14 and PyPy 3.11.

## Where the oracles overruled the brief

1. **HALT is two cycles when it halts, one when it does not.** The brief said a halted CPU does
   "exactly one `idle(PC)`" and HALT is its fetch. The die shows HALT's own M-cycle as a read of the
   next byte (PC not advanced) before the clock stops, the HALT bug as a single cycle, and the
   decision as made on the interrupt state before the HALT's fetch.
2. **Halted and locked cycles drive `$0000`, not PC.** Both die models.
3. **A halted CPU wakes in the cycle after IF rises**, with no idle cycle first (dmg-sim).
4. **`JR`'s internal cycle drives `{PCH, $00}`.** GBCTR's "PCH" is literal.
5. **`EI; HALT` with an interrupt pending** has its own bus shape (`halt_dispatch` in the state).
6. `ie` is seeded from the corpus's RAM at `$FFFF` in the SingleStepTests runner, because the core
   owns `$FFFF` and the corpus treats it as RAM.

Everything else in the brief held: the fetch-first `step()`, one callback per M-cycle with
internal cycles, IE and IF on the core with `request_interrupt` and its visibility rule, the
STOP hook, and the oracle tiers.

## Not done

- **STOP** has the hook and the decode, but no oracle exercised it: the mock SoC has no joypad or
  KEY1, and nothing pinned here tests DMG stop mode. dmg-sim could (a joypad line in the probe
  ROM); not run.
- **Rung 6** (blargg 02, `instr_timing`, `mem_timing`, `halt_bug`, `oam_bug`, Mooneye's timing
  tests, Gambatte's `halt`, `irq_precedence`, `undef_ops`, `speedchange`) is the board's; failures
  that are the core's come back here as issues.
- **The DMG/CGB two-T-cycle difference in leaving HALT** is sub-M-cycle and the board's.
- No GitHub repository, tag or CI yet, by the brief's rule (local until rung 3 passes; it has).
  Both came the same day; there is still no tag or release.
