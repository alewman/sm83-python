#!/usr/bin/env python3
"""Turn a dmg-sim probe log (scripts/dmgsim_run.py) into one bus row per M-cycle.

An M-cycle is one period of ``phi`` while the CPU runs (952 ns in dmg-sim; measured from the
log, not assumed). Within it the address settles early, the data bus and the read or write
strobe come in the second half, and the strobe ends just after the cycle's end. So a row is
the state of the SM83 core's own signals *immediately before* the end of each cycle: kind from
``rd``/``wr`` (neither: an internal cycle), the address and data of the core's ports, ``m1`` the
fetch flag, and the interrupt-flag bits IF.

The cycle boundaries are a fixed grid, not the edges of ``phi``: the simulator stops ``phi``
while the CPU is halted, so counting its edges would skip the whole halt. The grid starts at
the end of the first fetch from $0100. ``running`` is false for a cycle in which ``phi`` made
no edge (the CPU's clock was stopped), true otherwise.
"""

from __future__ import annotations

from bisect import bisect_left
from itertools import pairwise
from pathlib import Path

Row = tuple[str, int, int | None, bool, bool, int]  # kind, address, data, m1, running, IF


def read_rows(path: Path) -> list[Row]:
    times: list[int] = []
    lines: list[list[str]] = []
    with path.open() as stream:
        for line in stream:
            fields = line.split()
            if len(fields) == 10 and fields[0].isdigit():
                times.append(int(fields[0]))
                lines.append(fields)
    # the end of the first fetch from $0100: the first rising edge of phi after it began
    first = next(
        (
            i
            for i in range(1, len(lines))
            if lines[i - 1][1] == "0"
            and lines[i][1] == "1"
            and lines[i - 1][2] == "0100"
            and lines[i - 1][6] == "1"
            and lines[i - 1][3] == "1"
        ),
        None,
    )
    if first is None:
        return []
    start = times[first]
    edge_list = [
        times[i] for i in range(1, len(lines)) if lines[i - 1][1] == "0" and lines[i][1] == "1"
    ]
    edges = set(edge_list)
    diffs = sorted(b - a for a, b in pairwise(edge_list) if 900 < b - a < 1000)
    period = diffs[len(diffs) // 2]  # the running phi period, 952 ns
    rows: list[Row] = []
    k = 0
    while True:
        end = start + k * period
        index = bisect_left(times, end - 0.5) - 1  # the last line strictly before the boundary
        if index < 0 or end > times[-1]:
            break
        _, _, a, rd, wr, _, m1, _, d, iflag = lines[index]
        try:
            address = int(a, 16)
        except ValueError:
            address = -1
        try:
            data: int | None = int(d, 16)
        except ValueError:
            data = None
        try:
            flags = int(iflag, 16)
        except ValueError:
            flags = 0
        kind = "write" if wr == "1" else "read" if rd == "1" else "internal"
        # phi rose within a couple of nanoseconds of this boundary: the CPU's clock was running
        running = any(abs(e - end) <= 3 for e in edges if end - 5 <= e <= end + 5)
        rows.append((kind, address, data, m1 == "1", running, flags))
        k += 1
    return rows


if __name__ == "__main__":
    import sys

    for row in read_rows(Path(sys.argv[1]))[: int(sys.argv[2]) if len(sys.argv) > 2 else 20]:
        print(row)
