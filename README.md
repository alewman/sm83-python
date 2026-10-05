# sm83-python

A readable, pure-Python **Sharp SM83** CPU core: the processor inside the Game
Boy, Game Boy Pocket, Super Game Boy, Game Boy Color and the Game Boy Advance's
backward-compatible mode. "LR35902" is the name of the original Game Boy's
whole system-on-a-chip; the CPU inside it is the SM83, and this repository is
only the CPU. The board, [gameboy-python](../gameboy-python), owns everything
else.

**Status (2026-10-05): groundwork only, no core code.** The documents in
[`docs/`](docs/README.md) gather what the build needs, every fact with its
source and tier: the instruction set, every M-cycle with its address,
interrupts, HALT and STOP, the quirks and contradictions, the oracles with
measured results, a verified MAME recipe, and the brief for the session that
builds the core ([docs/handoff-brief.md](docs/handoff-brief.md)).

The core will follow [z80-python](https://github.com/alewman/z80-python)'s
shape: host-owned memory passed in as callables, `step()` returning M-cycles,
no dependencies, CPython and PyPy (Python 3.11+). Unlike z80-python it will make
**one bus callback per M-cycle, internal cycles included**, because the Game
Boy's hardware reacts to the address the CPU drives even when it neither reads
nor writes (the DMG's OAM corruption bug).

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
| `scripts/mame_trace.py` | MAME 0.285 per-instruction trace and serial output of a Game Boy ROM, with a free boot ROM ([docs/mame-oracle.md](docs/mame-oracle.md)) |

## Licence

MIT (see `LICENSE`), for what is in this repository. The fetched material keeps
its own terms, recorded per entry in the pin lists.
