"""Precomputed attack tables: knight, king, pawn (per color), and sliding rays.

Sliding pieces use ray-walk on demand against the current occupancy. We
precompute the *ray squares* in each direction from each square so the inner
loop does no arithmetic.
"""

from __future__ import annotations
from .types import WHITE, BLACK, sq, file_of, rank_of

# ---------------------------------------------------------------------------
# Leaper tables (knight, king, pawn captures)
# ---------------------------------------------------------------------------

def _gen_knight_attacks():
    table = [0] * 64
    offsets = [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]
    for s in range(64):
        f, r = file_of(s), rank_of(s)
        targets = []
        for df, dr in offsets:
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                targets.append(sq(nf, nr))
        table[s] = tuple(targets)
    return table

def _gen_king_attacks():
    table = [0] * 64
    offsets = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
    for s in range(64):
        f, r = file_of(s), rank_of(s)
        targets = []
        for df, dr in offsets:
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                targets.append(sq(nf, nr))
        table[s] = tuple(targets)
    return table

def _gen_pawn_attacks():
    """pawn_attacks[color][sq] = tuple of squares that pawn ATTACKS (diagonals only)."""
    table = [[() for _ in range(64)], [() for _ in range(64)]]
    for s in range(64):
        f, r = file_of(s), rank_of(s)
        # White pawn attacks: forward-left and forward-right (one rank up)
        w = []
        for df, dr in ((-1, 1), (1, 1)):
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                w.append(sq(nf, nr))
        table[WHITE][s] = tuple(w)
        # Black pawn attacks: one rank down
        b = []
        for df, dr in ((-1, -1), (1, -1)):
            nf, nr = f + df, r + dr
            if 0 <= nf < 8 and 0 <= nr < 8:
                b.append(sq(nf, nr))
        table[BLACK][s] = tuple(b)
    return table

KNIGHT_ATTACKS = _gen_knight_attacks()
KING_ATTACKS   = _gen_king_attacks()
PAWN_ATTACKS   = _gen_pawn_attacks()

# ---------------------------------------------------------------------------
# Sliding rays
# rays[direction_idx][sq] = tuple of squares in that direction, from nearest to farthest
# ---------------------------------------------------------------------------
ROOK_DIRS   = ((0, 1), (0, -1), (1, 0), (-1, 0))         # N, S, E, W
BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))       # NE, SE, NW, SW

def _gen_rays(directions):
    out = [[() for _ in range(64)] for _ in directions]
    for di, (df, dr) in enumerate(directions):
        for s in range(64):
            f, r = file_of(s), rank_of(s)
            ray = []
            while True:
                f += df
                r += dr
                if not (0 <= f < 8 and 0 <= r < 8):
                    break
                ray.append(sq(f, r))
            out[di][s] = tuple(ray)
    return out

ROOK_RAYS   = _gen_rays(ROOK_DIRS)
BISHOP_RAYS = _gen_rays(BISHOP_DIRS)
