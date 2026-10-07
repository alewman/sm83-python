"""The SM83 flag register: Z N H C in bits 7-4, bits 3-0 always zero."""

from enum import IntFlag


class Flags(IntFlag):
    """Bits of the F register. The low nibble does not exist: it always reads 0 (U1)."""

    Z = 0x80
    N = 0x40
    H = 0x20
    C = 0x10


FLAG_Z = int(Flags.Z)
FLAG_N = int(Flags.N)
FLAG_H = int(Flags.H)
FLAG_C = int(Flags.C)

__all__ = ["FLAG_C", "FLAG_H", "FLAG_N", "FLAG_Z", "Flags"]
