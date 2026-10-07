# sm83-python

A readable, pure-Python **Sharp SM83** CPU core: the processor inside the Game
Boy, Game Boy Pocket, Super Game Boy, Game Boy Color and the Game Boy Advance's
backward-compatible mode. "LR35902" is the name of the original Game Boy's
whole system-on-a-chip; the CPU inside it is the SM83, and this repository is
only the CPU. The board, [gameboy-python](../gameboy-python), owns everything
else.

**Status (2026-10-07): built, local.** The core passes rungs 0-5 of
[docs/validation.md](docs/validation.md): the bus schedule of every opcode against GBCTR;
SingleStepTests sm83 (498,000 cases); blargg `cpu_instrs` and the board-free Mooneye ROMs; about 6
million instructions of real code replayed against MAME; and cycle-for-cycle agreement with **two
independent die-traced models** (Gekkio's VHDL SM83 and msinger's dmg-sim) on every opcode, both
paths of every conditional, and HALT being woken. Rung 6 (blargg `instr_timing`, `halt_bug`,
`oam_bug`, Mooneye's timing tests, Gambatte) is the board's. What was built, what the oracles
changed relative to the brief, and what is left: [docs/build-log.md](docs/build-log.md).

```python
from sm83_python import SM83

memory = bytearray(0x10000)
cpu = SM83(memory.__getitem__, memory.__setitem__)  # idle=..., stop=... are optional
cycles = cpu.step()  # M-cycles consumed == bus callbacks made
```

The shape follows [z80-python](https://github.com/alewman/z80-python): host-owned memory passed in
as callables, `step()` returning M-cycles, no dependencies, CPython and PyPy (Python 3.11+). Unlike
z80-python it makes **one bus callback per M-cycle, internal cycles included**
(`idle(address)`, and `cpu.idu` says whether the increment/decrement unit moved that address),
because the Game Boy's hardware reacts to the address the CPU drives even when it neither reads nor
writes (the DMG's OAM corruption bug). `ie` and `if_` are attributes of the core, which owns
`$FFFF`; the board raises interrupts with `cpu.request_interrupt(bit)` and answers `STOP` through a
hook. The host advances its devices inside the callbacks, never by adding `step()`'s return value.

```sh
python -m sm83_python ROM.gb [--boot BOOT] [--max-cycles N] [--trace out.jsonl] [--debug]
python -m pytest -m "not slow"     # seconds; plain `pytest` adds the full corpora and simulators
```

## What is fetched

Nothing third-party is committed. `scripts/fetch_references.py` rebuilds
`reference/` from `scripts/pinned_files.json` (5 files pinned by SHA-256: the
built Mooneye ROMs, GBCTR's PDF, the SonoSooS CPU-internals notes, and two tool
bundles) and `scripts/pinned_repos.json` (16 repositories at full commit SHAs,
sparse where large), including SingleStepTests sm83, blargg's and Mooneye's
test ROMs, Gambatte's hardware-captured tests, SameBoy, Pan Docs, GBCTR, and two
die-traced SM83 models.

```sh
python scripts/fetch_references.py              # everything missing (~1 GB)
python scripts/fetch_references.py --no-tools   # without the 750 MB simulator bundle
python scripts/fetch_references.py --verify     # check what is present
python scripts/build_referees.py                # SameBoy tester, GHDL venv, dmg-sim
python scripts/gbctr_timing.py                  # tests/gbctr_timing.json
```

They need `git`, `curl`, `make`, a C compiler, and `uv` for the GHDL venv.
No sudo.

## Scripts

| Script | What |
| --- | --- |
| `scripts/fetch_references.py` | the pinned references, test ROMs and tool bundles |
| `scripts/build_referees.py` | builds SameBoy's headless tester and free boot ROMs, a venv for Gekkio's die-traced VHDL SM83, and msinger's dmg-sim |
| `scripts/gbctr_timing.py` | GBCTR's per-M-cycle tables (address, data, IDU, ALU, access kind) as JSON |
| `scripts/mame_trace.py` | MAME 0.285 per-instruction trace and serial output of a Game Boy ROM, with a free boot ROM; `--io` adds the I/O read log the replay needs ([docs/mame-oracle.md](docs/mame-oracle.md)) |
| `scripts/gen_opcode_table.py` | generates `src/sm83_python/_opcodes.py` from GBCTR's `opcodes.toml` and `gb-opcodes`, cross-checked |
| `scripts/die_programs.py`, `die_run.py`, `die_compare.py`, `die_halt.py` | the all-opcodes ROM, a bus-dump testbench for Gekkio's VHDL SM83, and the cycle-for-cycle comparison with the core |
| `scripts/dmgsim_run.py`, `dmgsim_rows.py`, `dmgsim_halt.py` | the same against msinger's dmg-sim, plus HALT woken by the timer |

## Licence

MIT (see `LICENSE`), for what is in this repository. The fetched material keeps
its own terms, recorded per entry in the pin lists.
