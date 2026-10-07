"""A minimal host that is not a Game Boy: just enough board to run test ROMs on the core.

Modelled on Gekkio's mock SoC (``gb-research/sm83-cpu-core/hdl/simulation/test_soc.vhd``),
which runs the same ROMs on the die model: ROM at $0000-$7FFF with an MBC1-style bank register
(enough for the 64 KiB ``cpu_instrs.gb``), RAM everywhere else, ``LY`` ($FF44) always $90, the
serial port, and $FF0F / $FFFF wired to the core's ``if_`` and ``ie``. **No timer (TIMA), no PPU**:
tests that need them belong to the board (validation.md rung 6).

The serial port is a little more than the mock SoC's constant $7F: a write of $81 to SC starts
an internal-clock transfer that completes after 8 bits (128 M-cycles each) by appending SB to
the collected text, clearing SC bit 7, loading SB with $FF (no peer) and raising IF bit 3.
Mooneye's ROMs that wait on the serial *interrupt* hung on the constant-$7F mock SoC
(validation.md); this port is what they need.

A run ends on ``LD B,B`` with Mooneye's result (pass = B,C,D,E,H,L = 3,5,8,13,21,34, fail
= all $42), on
a jump or ``JR`` to itself (blargg's end of test), or at a cycle budget. ``LD B,B`` only ends
a run when the registers hold Mooneye's pass or fail pattern (blargg's ``06-ld r,r`` executes
it too).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sm83_python.cpu import SM83, CPUState

#: DMG registers at $0100 (Pan Docs Power_Up_Sequence.md "CPU registers"); F depends on the
#: cartridge header checksum, see :func:`post_boot_state`.
MOONEYE_PASS = (3, 5, 8, 13, 21, 34)
SERIAL_CYCLES = 8 * 128  # internal clock: 8192 bit/s = 512 T-cycles = 128 M-cycles per bit

SB, SC, DIV, IF_REGISTER, LY, BOOT_DISABLE = 0xFF01, 0xFF02, 0xFF04, 0xFF0F, 0xFF44, 0xFF50


def post_boot_state(rom: bytes) -> CPUState:
    """The DMG's registers as the boot ROM leaves them: H and C of F follow the checksum."""
    header_checksum = rom[0x014D] if len(rom) > 0x014D else 0
    return CPUState(
        a=0x01,
        f=0x80 if header_checksum == 0 else 0xB0,
        c=0x13,
        e=0xD8,
        h=0x01,
        l=0x4D,
        sp=0xFFFE,
        pc=0x0100,
        if_=0x01,  # IF reads $E1 after the boot ROM: VBlank pending
    )


@dataclass(frozen=True)
class RunResult:
    """Why a run ended and what it produced."""

    reason: str  # "ld b,b", "jump to self", "budget" or "locked"
    cycles: int
    instructions: int
    text: str  # everything the ROM wrote to the serial port
    registers: tuple[int, ...]  # B, C, D, E, H, L at the end

    @property
    def mooneye_passed(self) -> bool:
        return self.reason == "ld b,b" and self.registers == MOONEYE_PASS


class Harness:
    """ROM, RAM, serial port and an SM83, wired together."""

    def __init__(self, rom: bytes, boot: bytes | None = None) -> None:
        self.rom = bytes(rom) + bytes(max(0, 0x8000 - len(rom)))
        self.rom_banks = max(1, len(self.rom) // 0x4000)
        self.bank = 1
        self.memory = bytearray(0x10000)
        self.boot = boot
        self.boot_enabled = boot is not None
        self.cycles = 0
        self.serial_text = bytearray()
        self.serial_data = 0
        self.serial_done_at: int | None = None
        self.div_origin = 0  # the M-cycle at which DIV was last reset
        self.cpu = SM83(self.read, self.write, self.idle)
        if boot is None:
            self.cpu.restore_state(post_boot_state(rom))
        else:
            self.cpu.reset()

    # ----- the memory map -------------------------------------------------

    def _tick(self) -> None:
        """One M-cycle passes: the only device is the serial port's bit clock."""
        self.cycles += 1
        if self.serial_done_at is not None and self.cycles >= self.serial_done_at:
            self.serial_done_at = None
            self.serial_text.append(self.serial_data)
            self.memory[SC] &= 0x7F
            self.serial_data = 0xFF  # no peer: the shift register fills with ones
            self.cpu.request_interrupt(3)

    def read(self, address: int) -> int:
        self._tick()
        if address < 0x4000:
            if self.boot_enabled and address < 0x100:
                return self.boot[address]  # type: ignore[index]
            return self.rom[address]
        if address < 0x8000:
            return self.rom[self.bank * 0x4000 + address - 0x4000]
        if address == DIV:  # the upper byte of a 16-bit counter that ticks every T-cycle
            return ((self.cycles - self.div_origin) * 4 >> 8) & 0xFF
        if address == LY:
            return 0x90  # vblank forever, as on the mock SoC
        if address == SB:
            return self.serial_data
        if address == SC:
            return self.memory[SC] | 0x7E
        if address == IF_REGISTER:
            return self.cpu.if_ | 0xE0  # the upper three bits read 1 (Mooneye if_ie_registers)
        if address == 0xFF00:
            return 0xFF  # no button pressed
        return self.memory[address]

    def write(self, address: int, value: int) -> None:
        self._tick()
        if address < 0x8000:
            if 0x2000 <= address < 0x4000:  # MBC1 bank register: 0 selects bank 1
                self.bank = (value & 0x1F or 1) % self.rom_banks
            return
        if address == DIV:
            self.div_origin = self.cycles  # any write resets the divider
        elif address == SB:
            self.serial_data = value
        elif address == SC:
            self.memory[SC] = value
            if value & 0x81 == 0x81:
                self.serial_done_at = self.cycles + SERIAL_CYCLES
        elif address == IF_REGISTER:
            self.cpu.if_ = value & 0x1F
        elif address == BOOT_DISABLE and value:
            self.boot_enabled = False
        else:
            self.memory[address] = value

    def idle(self, address: int) -> None:
        self._tick()

    # ----- running --------------------------------------------------------

    def peek(self, address: int) -> int:
        """A byte as the CPU would read it, without making a bus cycle."""
        if address < 0x4000:
            return (
                self.boot[address] if self.boot_enabled and address < 0x100 else self.rom[address]
            )  # type: ignore[index]
        if address < 0x8000:
            return self.rom[self.bank * 0x4000 + address - 0x4000]
        return self.memory[address]

    def _ends_here(self) -> str | None:
        """The stop condition of the instruction about to execute, if it is one."""
        pc = self.cpu.pc
        opcode = self.peek(pc)
        if opcode == 0x40:  # blargg's own tests execute LD B,B too: only Mooneye's result counts
            registers = (self.cpu.b, self.cpu.c, self.cpu.d, self.cpu.e, self.cpu.h, self.cpu.l)
            if registers in (MOONEYE_PASS, (0x42,) * 6):
                return "ld b,b"
        if opcode == 0x18 and self.peek(pc + 1) == 0xFE:
            return "jump to self"
        if opcode == 0xC3 and self.peek(pc + 1) | self.peek(pc + 2) << 8 == pc:
            return "jump to self"
        return None

    def run(
        self, max_cycles: int = 100_000_000, step: Callable[[], object] | None = None
    ) -> RunResult:
        """Step until a stop condition or ``max_cycles`` M-cycles. ``step`` replaces
        ``cpu.step`` (a debug session's ``step`` records the trace as it goes)."""
        cpu = self.cpu
        advance = step or cpu.step
        instructions = 0
        reason = "budget"
        while self.cycles < max_cycles:
            if cpu.locked:
                reason = "locked"
                break
            if not (cpu.halted or cpu.stopped):
                found = self._ends_here()
                if found:
                    reason = found
                    break
            advance()
            instructions += 1
        return RunResult(
            reason,
            self.cycles,
            instructions,
            self.serial_text.decode("ascii", "replace"),
            (cpu.b, cpu.c, cpu.d, cpu.e, cpu.h, cpu.l),
        )


__all__ = ["MOONEYE_PASS", "Harness", "RunResult", "post_boot_state"]
