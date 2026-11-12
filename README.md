# sm83-python

A readable, pure-Python **Sharp SM83** CPU core: the processor inside the Game
Boy, Game Boy Pocket, Super Game Boy, Game Boy Color and the Game Boy Advance's
backward-compatible mode. "LR35902" is the name of the original Game Boy's
whole system-on-a-chip; the CPU inside it is the SM83, and this repository is
only the CPU.

It is one of a family of reference cores: chips are cores, boards compose them, and every
behaviour names the source it was judged against. Correctness and readability come before speed.
The board [gameboy-python](https://github.com/alewman/gameboy-python) is built on it and owns
everything else on the chip (picture, sound, timer, serial, joypad, DMA, boot ROM, memory map).

## Status

Rungs 0-5 of [docs/validation.md](docs/validation.md) pass, each against a higher tier of oracle
than the one before:

| Rung | Judge | Result |
| --- | --- | --- |
| 0 | GBCTR's per-M-cycle tables | the bus schedule (kind, address, IDU direction) of all 514 opcode paths |
| 1 | SingleStepTests sm83 (emulator-derived) | 498 files, 498,000 cases; adtennant v2: 241 files |
| 2 | blargg `cpu_instrs` (hardware-verified) | 01 and 03-11 `Passed` in the minimal harness (02 needs a timer) |
| 3 | Mooneye (hardware-verified) | `daa`, `reg_f`, `ie_push`, the EI/DI/RETI and dispatch-timing ROMs: 15 of the 75 acceptance ROMs pass in the harness; the rest need a timer, PPU or OAM DMA |
| 4 | MAME 0.285 replay (emulator-derived) | no divergence over blargg `03` and six commercial games, 6.5 million instructions |
| 5 | Gekkio's VHDL SM83 and msinger's dmg-sim (two independent die tracings) | every M-cycle of 533 cases (every opcode, both paths, dispatch) agrees with each; HALT entry and wake-up |

The die models corrected the bus in five places the documents had wrong or left open (`JR`'s
internal cycle, the halted and locked address, HALT's two cycles, the wake, `EI; HALT`);
[docs/build-log.md](docs/build-log.md) lists them. Rung 6 (blargg `instr_timing`, `halt_bug`,
`oam_bug`, Mooneye's timing tests, Gambatte's `halt` and `irq_precedence`) needs a whole Game Boy
and runs on gameboy-python; the two keyword arguments of `request_interrupt` below came back from
it. STOP has its decode and a board hook, but no oracle here exercises it.

The quick suite (`pytest -m "not slow"`, 1,478 tests) runs in CI on PyPy; the corpora, MAME and
the die models are local runs (`pytest -m slow`) and skip without the fetched references.

## Use

Not on PyPI. From a clone, on CPython or PyPy 3.11 or newer; there are no dependencies:

```sh
pip install -e '.[dev]'
```

```python
from sm83_python import SM83

memory = bytearray(0x10000)
cpu = SM83(memory.__getitem__, memory.__setitem__)  # idle=..., stop=... are optional
cycles = cpu.step()  # M-cycles consumed == bus callbacks made
```

The shape follows [z80-python](https://github.com/alewman/z80-python): host-owned memory passed in
as callables, `step()` returning M-cycles. Unlike z80-python it makes **one bus callback per
M-cycle, internal cycles included** (`idle(address)`, and `cpu.idu` says whether the
increment/decrement unit moved that address), because the Game Boy's hardware reacts to the
address the CPU drives even when it neither reads nor writes (the DMG's OAM corruption bug). The
host advances its devices inside the callbacks, never by adding `step()`'s return value.

`ie` and `if_` are attributes of the core, which owns `$FFFF`. The board raises interrupts with
`cpu.request_interrupt(bit)`, from any callback; a request is seen by every decision the core
takes after that callback returns. Two flags place a request within its M-cycle, which the core
alone cannot: `halt_sees=True` (raised early enough for a HALT fetched in that cycle to see it)
and `late=True` (raised after the dispatch's IF sample, so that dispatch does not choose it).
[docs/timing.md](docs/timing.md) "HALT" and "Interrupt dispatch" give the rules and the hardware
tests behind them. `STOP` is answered by the board through the `stop` hook.

The command line runs a ROM in the minimal harness (ROM, RAM, a serial port and DIV; no timer or
PPU) and prints its serial output:

```sh
python -m sm83_python ROM.gb [--boot BOOT] [--max-cycles N] [--trace out.jsonl] [--debug]
python -m pytest -m "not slow"     # under a minute; plain `pytest` adds the corpora and simulators
```

## Documents

[docs/README.md](docs/README.md) is the index: the SM83 as a core author needs it, every M-cycle
with its address, the undocumented behaviour and where sources disagree, every oracle with its
tier and pin, the MAME recipe, and the trace format.

## What is fetched

Nothing third-party is committed except `scripts/die/test_soc_irq.vhd`, a modified copy of
Gekkio's mock SoC (MIT OR Apache-2.0, notice in the file). `scripts/fetch_references.py` rebuilds
`reference/` from `scripts/pinned_files.json` (5 files pinned by SHA-256: the built Mooneye ROMs,
GBCTR's PDF, the SonoSooS CPU-internals notes, and two tool bundles) and
`scripts/pinned_repos.json` (16 repositories at full commit SHAs, sparse where large), including
SingleStepTests sm83, blargg's and Mooneye's test ROMs, Gambatte's hardware-captured tests,
SameBoy, Pan Docs, GBCTR, and two die-traced SM83 models. No boot ROM is needed: the harness
starts at `$0100`, and MAME runs with SameBoy's free boot ROM.

```sh
python scripts/fetch_references.py              # everything missing (~1 GB)
python scripts/fetch_references.py --no-tools   # without the 750 MB simulator bundle
python scripts/fetch_references.py --verify     # check what is present
python scripts/build_referees.py                # SameBoy tester, GHDL venv, dmg-sim
python scripts/gbctr_timing.py                  # tests/gbctr_timing.json
```

They need `git`, `curl`, `make`, a C compiler, and `uv` for the GHDL venv; MAME 0.285 for rung 4
(`$MAME`, else `mame` on `PATH`). No sudo.

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

## Credits

The core rests on other people's research, each cited where it is used: Gekkio's
[Game Boy: Complete Technical Reference](https://github.com/Gekkio/gb-ctr), his
[Mooneye Test Suite](https://github.com/Gekkio/mooneye-test-suite) and his die-traced VHDL SM83
([gb-research](https://github.com/Gekkio/gb-research)); msinger's
[dmg-sim](https://github.com/msinger/dmg-sim) and DMG schematics; SonoSooS's *Gameboy CPU
internals*; [Pan Docs](https://github.com/gbdev/pandocs); blargg's test ROMs;
[SingleStepTests sm83](https://github.com/SingleStepTests/sm83);
[SameBoy](https://github.com/LIJI32/SameBoy) and [SameSuite](https://github.com/LIJI32/SameSuite);
Gambatte's hardware tests; and [gb-opcodes](https://github.com/gbdev/gb-opcodes).

## Licence

MIT (see `LICENSE`), for what is in this repository. The fetched material keeps
its own terms, recorded per entry in the pin lists.
