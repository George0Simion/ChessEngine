"""Zobrist hashing tables.

We use a fixed seed so hashes are stable across runs (helps caching/debug).
"""

from __future__ import annotations
import random

_RNG = random.Random(0xC0FFEE_C5_BABE)

def _rand64() -> int:
    return _RNG.getrandbits(64)

# Piece keys: indexed by piece code (0-13). Empty (0) is unused.
PIECE_KEYS = [[_rand64() for _ in range(64)] for _ in range(14)]
# Side-to-move flip (only when it's black to move).
SIDE_KEY = _rand64()
# Castling rights: indexed by 4-bit mask (0..15).
CASTLE_KEYS = [_rand64() for _ in range(16)]
# En-passant file (0..7); we only mix in EP when an EP capture is actually
# possible for the side to move, but storing per-file keys is enough.
EP_FILE_KEYS = [_rand64() for _ in range(8)]
