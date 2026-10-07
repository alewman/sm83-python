"""Behaviour the corpora cannot reach: dispatch, HALT, EI/DI, STOP, the holes, $FFFF.

Every expectation cites the document item it comes from (docs/timing.md, docs/start-here.md,
docs/undocumented-behavior.md U-items). These are unit tests of documented rules, not oracle
runs: the hardware-verified judges for the same rules are Mooneye and blargg (rungs 2-3).
"""

from __future__ import annotations

import pytest

from sm83_python import SM83, CPUState, StopAction, StopResult


class Host:
    """64 KiB RAM with a log of (kind, address, idu) and an optional per-cycle hook."""

    def __init__(self, **kwargs) -> None:
        self.memory = bytearray(0x10000)
        self.log: list[tuple[str, int, int]] = []
        self.on_cycle = None
        self.cpu = SM83(self.read, self.write, self.idle, **kwargs)

    def load(self, address: int, *data: int) -> None:
        self.memory[address : address + len(data)] = bytes(data)

    def _record(self, kind: str, address: int) -> None:
        self.log.append((kind, address, self.cpu.idu))
        if self.on_cycle:
            self.on_cycle(len(self.log), kind, address)

    def read(self, address: int) -> int:
        self._record("read", address)
        return self.memory[address]

    def write(self, address: int, value: int) -> None:
        self._record("write", address)
        self.memory[address] = value

    def idle(self, address: int) -> None:
        self._record("internal", address)

    def run(self, steps: int) -> list[int]:
        return [self.cpu.step() for _ in range(steps)]


def host_at(pc: int = 0x0200, sp: int = 0xC100, **state) -> Host:
    host = Host()
    host.cpu.restore_state(CPUState(pc=pc, sp=sp, **state))
    return host


# ----- the 11 holes lock the CPU (U3) ---------------------------------------


@pytest.mark.parametrize(
    "opcode", [0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD]
)
def test_holes_lock_the_cpu_and_nothing_wakes_it(opcode):
    host = host_at(ie=0x01, if_=0x01, ime=True)
    host.load(0x0200, opcode)
    host.cpu.if_ = 0
    assert host.cpu.step() == 1
    assert host.cpu.locked
    host.cpu.if_ = 0x01  # a pending, enabled interrupt with IME = 1 is never serviced
    pc = host.cpu.pc
    host.log.clear()
    assert host.run(5) == [1] * 5
    assert host.log == [("internal", pc, 0)] * 5
    assert host.cpu.pc == pc and host.cpu.sp == 0xC100


# ----- interrupt dispatch (timing.md "Interrupt dispatch") ------------------


def test_dispatch_is_five_cycles_with_the_documented_bus():
    host = host_at(pc=0x1234, sp=0xC100, ie=0x04, if_=0x04, ime=True)
    assert host.cpu.step() == 5
    assert host.log == [
        ("read", 0x1234, 1),  # M1 the discarded fetch
        ("internal", 0x1235, -1),  # M2 the IDU puts PC back
        ("internal", 0xC100, -1),  # M3 SP - 1
        ("write", 0xC0FF, -1),  # M4 PCH
        ("write", 0xC0FE, 0),  # M5 PCL
    ]
    assert host.memory[0xC0FF] == 0x12 and host.memory[0xC0FE] == 0x34
    state = host.cpu.capture_state()
    assert (state.pc, state.sp, state.ime, state.if_) == (0x50, 0xC0FE, False, 0)


@pytest.mark.parametrize("bit", range(5))
def test_vector_is_the_lowest_pending_bit(bit):
    host = host_at(ie=0x1F, if_=(1 << bit) | 0x10 if bit < 4 else 0x10, ime=True)
    host.cpu.step()
    expected_bit = bit if bit < 4 else 4
    assert host.cpu.pc == 0x40 + 8 * expected_bit


def test_dispatch_needs_ie_and_ime():
    for ie, ime in ((0x00, True), (0x01, False)):
        host = host_at(ie=ie, if_=0x01, ime=ime)
        host.load(0x0200, 0x00)
        assert host.cpu.step() == 1  # a NOP, not a dispatch
        assert host.cpu.pc == 0x0201


def test_ie_push_cancels_the_dispatch_and_sends_pc_to_zero():
    # U8, Mooneye ie_push (hardware-verified, all models): SP = 0 puts the high-byte push at
    # $FFFF; PCH = 0 there clears IE, nothing is left pending, PC = $0000, IF untouched.
    host = host_at(pc=0x0000, sp=0x0000, ie=0x01, if_=0x01, ime=True)
    assert host.cpu.step() == 5
    state = host.cpu.capture_state()
    assert (state.pc, state.ie, state.if_, state.ime) == (0x0000, 0x00, 0x01, False)


def test_ie_push_with_a_higher_priority_source_picks_it():
    # PCH = $01 written to IE leaves only VBlank enabled although the Joypad bit was pending.
    host = host_at(pc=0x0100, sp=0x0000, ie=0x10, if_=0x11, ime=True)
    host.cpu.step()
    assert host.cpu.pc == 0x0040 and host.cpu.if_ == 0x10 and host.cpu.ie == 0x01


def test_a_request_during_the_low_push_can_pick_the_vector():
    # brief: IF is sampled after the low-byte push, so a higher-priority request made in its
    # callback wins the vector; the lower-priority bit stays pending
    host = host_at(ie=0x05, if_=0x04, ime=True)
    host.on_cycle = lambda n, kind, address: n == 5 and host.cpu.request_interrupt(0)
    host.cpu.step()
    assert host.cpu.pc == 0x40 and host.cpu.if_ == 0x04


def test_a_request_during_a_step_is_seen_by_the_next_step_only():
    host = host_at(ie=0x01, ime=True)
    host.load(0x0200, 0x00, 0x00)
    host.on_cycle = lambda n, kind, address: n == 1 and host.cpu.request_interrupt(0)
    assert host.cpu.step() == 1  # the NOP executes; the request arrived after the decision
    assert host.cpu.step() == 5  # and is dispatched at the next step


def test_request_interrupt_rejects_other_bits():
    with pytest.raises(ValueError, match=r"0\.\.4"):
        host_at().cpu.request_interrupt(5)


# ----- EI, DI, RETI (U9; Mooneye ei_sequence, rapid_di_ei, reti_intr_timing) -


def test_ei_enables_after_the_following_instruction():
    host = host_at(ie=0x01, if_=0x01)
    host.load(0x0200, 0xFB, 0x00, 0x00)  # EI; NOP; NOP
    assert host.cpu.step() == 1
    assert host.cpu.ei_pending and not host.cpu.ime
    assert host.cpu.step() == 1  # the NOP after EI cannot be interrupted
    assert host.cpu.ime and host.cpu.pc == 0x0202
    assert host.cpu.step() == 5  # and the interrupt is taken before the next one
    assert host.cpu.pc == 0x40


def test_ei_then_di_lets_nothing_in():
    host = host_at(ie=0x01, if_=0x01)
    host.load(0x0200, 0xFB, 0xF3, 0x00)  # EI; DI; NOP
    assert host.run(3) == [1, 1, 1]
    assert not host.cpu.ime and host.cpu.pc == 0x0203


def test_di_is_immediate_and_cancels_a_pending_ei():
    host = host_at(ime=True)
    host.load(0x0200, 0xF3)
    host.cpu.step()
    assert not host.cpu.ime
    host = host_at(ei_pending=True)
    host.load(0x0200, 0xF3, 0x00)
    host.run(2)
    assert not host.cpu.ime


def test_reti_sets_ime_with_no_delay():
    host = host_at(sp=0xC000)
    host.load(0x0200, 0xD9)
    host.load(0xC000, 0x34, 0x12)
    assert host.cpu.step() == 4
    assert host.cpu.ime and not host.cpu.ei_pending and host.cpu.pc == 0x1234


# ----- HALT (start-here.md table; U4-U6, U14) ---------------------------------


def test_halt_ime1_no_pending_halts_then_dispatches_on_wake():
    host = host_at(ie=0x01, ime=True)
    host.load(0x0200, 0x76, 0x00)
    assert host.cpu.step() == 1 and host.cpu.halted and host.cpu.pc == 0x0201
    host.log.clear()
    assert host.run(3) == [1, 1, 1] and host.log == [("internal", 0x0201, 0)] * 3
    host.cpu.request_interrupt(0)
    assert host.cpu.step() == 6  # one halted cycle, then the five-cycle dispatch
    assert host.cpu.pc == 0x40 and not host.cpu.halted
    assert host.memory[0xC0FF] == 0x02 and host.memory[0xC0FE] == 0x01  # returns after HALT


def test_halt_ime0_no_pending_wakes_and_continues_without_dispatch():
    host = host_at(ie=0x01)
    host.load(0x0200, 0x76, 0x3C)  # HALT; INC A
    host.cpu.step()
    host.cpu.request_interrupt(0)
    assert host.cpu.step() == 1 and not host.cpu.halted
    host.cpu.step()
    assert host.cpu.a == 1 and host.cpu.pc == 0x0202 and host.cpu.if_ == 0x01


def test_halt_ime1_with_pending_does_not_halt_and_returns_to_the_halt():
    # U6: the dispatch happens at the HALT and pushes the HALT's own address
    host = host_at(ie=0x01, if_=0x01, ime=True)
    host.load(0x0200, 0x76)
    host.cpu.if_ = 0
    host.on_cycle = lambda n, kind, address: n == 1 and host.cpu.request_interrupt(0)
    assert host.cpu.step() == 1 and not host.cpu.halted and host.cpu.pc == 0x0200
    host.on_cycle = None
    assert host.cpu.step() == 5
    assert host.memory[0xC0FF] == 0x02 and host.memory[0xC0FE] == 0x00


def test_halt_bug_reads_the_next_byte_twice():
    # U4: IME = 0 with an interrupt pending at HALT: no halt, the next fetch does not
    # increment PC, so INC A executes twice.
    host = host_at(ie=0x01, if_=0x01)
    host.load(0x0200, 0x76, 0x3C)  # HALT; INC A
    assert host.cpu.step() == 1 and not host.cpu.halted and host.cpu.halt_bug
    host.cpu.step()
    assert host.cpu.pc == 0x0201 and host.cpu.a == 1 and not host.cpu.halt_bug
    host.cpu.step()
    assert host.cpu.pc == 0x0202 and host.cpu.a == 2


def test_ei_halt_with_pending_dispatches_and_returns_to_the_halt():
    # U5: EI; HALT with an interrupt pending is serviced and returns to the HALT
    host = host_at(ie=0x01, if_=0x01)
    host.load(0x0200, 0xFB, 0x76)
    host.run(2)  # EI; HALT (IME has just come on, so no HALT bug)
    assert not host.cpu.halted and not host.cpu.halt_bug and host.cpu.pc == 0x0201
    assert host.cpu.step() == 5
    assert host.memory[0xC0FF] == 0x02 and host.memory[0xC0FE] == 0x01


# ----- STOP (timing.md "STOP"; U11) -------------------------------------------


def test_default_stop_is_two_bytes_and_stops_until_if_changes():
    host = host_at()
    host.load(0x0200, 0x10, 0x00, 0x3C)
    assert host.cpu.step() == 2 and host.cpu.stopped and host.cpu.pc == 0x0202
    assert host.run(3) == [1, 1, 1] and host.cpu.stopped
    host.cpu.request_interrupt(4)
    assert host.cpu.step() == 1 and not host.cpu.stopped
    host.cpu.step()
    assert host.cpu.a == 1


@pytest.mark.parametrize(
    ("result", "cycles", "pc", "flags"),
    [
        (StopResult(StopAction.STOP), 2, 0x0202, {"stopped": True}),
        (StopResult(StopAction.STOP, consume_operand=False), 1, 0x0201, {"stopped": True}),
        (StopResult(StopAction.HALT), 2, 0x0202, {"halted": True}),
        (StopResult(StopAction.NOP, consume_operand=False), 1, 0x0201, {}),
    ],
)
def test_stop_hook_decides_the_outcome(result, cycles, pc, flags):
    seen = []
    host = Host(stop=lambda pending: seen.append(pending) or result)
    host.cpu.restore_state(CPUState(pc=0x0200, ie=0x01, if_=0x01))
    host.load(0x0200, 0x10, 0x00)
    assert host.cpu.step() == cycles and host.cpu.pc == pc
    assert seen == [True]  # pending = IE & IF & $1F != 0
    state = host.cpu.capture_state()
    assert (state.stopped, state.halted) == (
        flags.get("stopped", False),
        flags.get("halted", False),
    )


# ----- the core owns $FFFF (brief "Decisions") --------------------------------


def test_write_to_ffff_sets_ie_before_the_callback_returns_and_the_cycle_is_made():
    seen = []
    host = host_at(a=0x15, h=0xFF, l=0xFF)
    host.on_cycle = lambda n, kind, address: seen.append((kind, address, host.cpu.ie))
    host.load(0x0200, 0x77)  # LD (HL),A
    host.cpu.step()
    assert (("write", 0xFFFF, 0x15)) in seen  # ie already updated inside the write callback
    assert host.memory[0xFFFF] == 0x15  # and the callback was still made


def test_read_of_ffff_returns_ie_whatever_the_host_says():
    host = host_at(ie=0xE5, h=0xFF, l=0xFF)
    host.memory[0xFFFF] = 0x00
    host.load(0x0200, 0x7E)  # LD A,(HL)
    host.cpu.step()
    assert host.cpu.a == 0xE5 and ("read", 0xFFFF, 0) in host.log


# ----- state, reset, flags ----------------------------------------------------


def test_pop_af_drops_the_low_nibble():
    host = host_at(sp=0xC000)
    host.load(0x0200, 0xF1)
    host.load(0xC000, 0xFF, 0x12)
    host.cpu.step()
    assert host.cpu.af == 0x12F0  # U1


def test_reset_and_state_round_trip():
    host = host_at(a=1, f=0xB0, ime=True, ei_pending=True, halted=True, ie=0x1F, if_=0x03)
    host.cpu.reset()
    state = host.cpu.capture_state()
    assert (state.pc, state.ie, state.ime, state.ei_pending, state.halted) == (
        0,
        0,
        False,
        False,
        False,
    )
    assert state.a == 1 and state.f == 0xB0 and state.if_ == 0x03  # the rest is kept
    original = CPUState(a=9, f=0x50, sp=0xFFFE, pc=0x0150, ime=True, locked=True, stop_if=4)
    host.cpu.restore_state(original)
    assert host.cpu.capture_state() == original


@pytest.mark.parametrize(
    "bad", [{"a": 256}, {"pc": -1}, {"f": 0x01}, {"ime": 1}, {"ie": True * 300}]
)
def test_state_validation(bad):
    with pytest.raises(ValueError):
        CPUState(**bad)


def test_bus_arguments_must_be_callable():
    with pytest.raises(TypeError):
        SM83(None, lambda a, v: None)
    with pytest.raises(TypeError):
        SM83(lambda a: 0, lambda a, v: None, idle=1)
