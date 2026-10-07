"""What the board tells the core about a ``STOP`` (docs/timing.md "STOP").

The core cannot decide STOP alone: the outcome depends on the joypad lines, KEY1 and the
interrupt state (SameBoy ``stop()``, SonoSooS "NOP and STOP"). On ``$10`` the core calls
``stop(pending)`` and carries out the :class:`StopResult` the board returns. A board that
switches CPU speed does it inside the hook and then returns :attr:`StopAction.HALT`.
"""

from dataclasses import dataclass
from enum import Enum


class StopAction(Enum):
    """The state STOP leaves the core in."""

    STOP = "stop"  # enter stop mode: `stopped`, one idle cycle per step until the board wakes it
    HALT = "halt"  # behave as HALT: `halted`, waking on a pending interrupt
    NOP = "nop"  # behave as a NOP: execution continues


@dataclass(frozen=True, slots=True)
class StopResult:
    """The board's answer to a STOP: the action, and whether the second byte is consumed."""

    action: StopAction
    consume_operand: bool = True


__all__ = ["StopAction", "StopResult"]
