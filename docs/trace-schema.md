# Trace schema (version 1)

The family's schema (z80-python `docs/trace-schema.md`) with the SM83's units. A trace is the
observable behaviour of a core written down one processor boundary at a time; two cores that
produce equal traces for the same program and host are, as far as software can tell, the same CPU.
Everything here is implemented by `src/sm83_python/trace.py`; if the two disagree, the code is the
specification.

JSON Lines: UTF-8, one object per line, `\n` terminated, blank lines ignored. This package writes
sorted keys and no whitespace; readers must not depend on either. Records are aligned by line
position when compared; `sequence` is informational.

| Key | Type | Meaning |
| --- | --- | --- |
| `version` | integer | `1`. A reader rejects any other value. |
| `sequence` | integer >= 0 | Producer-local counter. |
| `kind` | string | `instruction`, `dispatch`, `halt_idle`, `stop_idle` or `locked_idle` (below). |
| `m_cycles` | integer > 0 | M-cycles the boundary consumed, exactly as `step()` returns them. |
| `instruction` | object or `null` | The instruction fetched; `null` for every other kind. |
| `before`, `after` | state object | Complete processor state at the boundary's start and end. |
| `accesses` | array, optional | Every M-cycle in order, as `[kind, address, value, idu]`. Absent means *not recorded*. |

No other keys are allowed.

## `accesses`

One entry per M-cycle, so `len(accesses) == m_cycles`. `kind` is `"read"`, `"write"` or
`"internal"`; `address` is what the CPU drove on the address bus (a cycle with no access still
drives one: `INC rr` drives `rr`, `PUSH` drives `SP`, `JP` drives `$0000`, a halted CPU drives
`$0000`); `value` is the byte moved, `null` for an internal cycle (a read of `$FFFF` records `ie`,
which the core owns); `idu` is `+1`, `-1` or `0`, what the increment/decrement unit did to the
address that cycle.

## `kind`

Decided from `before`, in this order: `locked` -> `locked_idle`; `stopped` -> `stop_idle`;
`halted` -> `halt_idle`; `ime` and `ie & if & $1F` -> `dispatch`; else `instruction`.

* `dispatch`: five M-cycles, the discarded fetch to the low-byte push.
* `halt_idle`: one halted cycle (`idle($0000)`, 1 M-cycle), or, when an interrupt is pending, the
  wake-up: a dispatch (5) or the fetch and execution of the next instruction, in the same step.
* `stop_idle`, `locked_idle`: one idle cycle.

## `instruction` and state

`instruction`: `address`, `data` (lowercase hex of every byte, prefix included), and optionally
`mnemonic` and `operands` (present together or absent together). **A producer in another language
should omit both**; the reader decodes the bytes with this package's disassembler.

State fields are those of `CPUState`: `a f b c d e h l sp pc ie if_ ime ei_pending halted halt_bug
halt_dispatch stopped locked stop_if`. `f` has bits 3..0 zero.
