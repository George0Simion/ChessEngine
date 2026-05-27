"""Static evaluation: material + PST (tapered) + mobility + bishop pair +
pawn structure + king safety + passed pawns + rook files + tempo.

All weights live in EVAL_WEIGHTS for easy tuning. Eval is always returned
from the side-to-move's perspective (positive = good for STM).
"""

from __future__ import annotations
from .types import (
    WHITE, BLACK, NO_PIECE, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING,
    piece_type, piece_color, sq, file_of, rank_of, make_piece,
)
from .attacks import KNIGHT_ATTACKS, KING_ATTACKS, ROOK_RAYS, BISHOP_RAYS
from .board import Position


# ---------------------------------------------------------------------------
# Tunable weights. Edit here, NOT scattered across the file.
# All values in centipawns. Bonuses are positive; penalties are negative.
# ---------------------------------------------------------------------------
EVAL_WEIGHTS = {
    # Material
    "pawn":   100,
    "knight": 320,
    "bishop": 330,
    "rook":   500,
    "queen":  900,

    # Pair / structure
    "bishop_pair":      30,
    "doubled_pawn":    -14,
    "isolated_pawn":   -16,
    "rook_open_file":   22,
    "rook_semi_open":   11,

    # Mobility (per legal target square)
    "mobility_knight": 4,
    "mobility_bishop": 4,
    "mobility_rook":   3,
    "mobility_queen":  1,

    # Passed pawns: indexed by rank from the pawn's color POV (0..7).
    # Heavily boosted in the endgame via passed_eg_scale.
    "passed_pawn":       (0, 5, 10, 20, 35, 60, 100, 0),
    "passed_eg_scale":   1.5,   # multiplier applied in EG component

    # King safety (MG-heavy; almost zero in EG where activity matters).
    "king_shield_pawn":   14,
    "king_attacker":      -9,   # per enemy-attacked square in king zone
    "king_open_file":    -24,   # missing pawn on king file or adjacent
    "tempo":              10,
}

# ---------- Material map ----------
MATERIAL = {
    PAWN:   EVAL_WEIGHTS["pawn"],
    KNIGHT: EVAL_WEIGHTS["knight"],
    BISHOP: EVAL_WEIGHTS["bishop"],
    ROOK:   EVAL_WEIGHTS["rook"],
    QUEEN:  EVAL_WEIGHTS["queen"],
    KING:   0,
}

# ---------- Piece-square tables (white POV, a1 = index 0) ----------
PST_PAWN = [
      0,   0,   0,   0,   0,   0,   0,   0,
      5,  10,  10, -22, -22,  10,  10,   5,
      5,  -5, -10,   0,   0, -10,  -5,   5,
      0,   0,   0,  22,  22,   0,   0,   0,
      5,   5,  10,  27,  27,  10,   5,   5,
     10,  10,  20,  32,  32,  20,  10,  10,
     50,  50,  50,  50,  50,  50,  50,  50,
      0,   0,   0,   0,   0,   0,   0,   0,
]

PST_KNIGHT = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20,   0,   5,   5,   0, -20, -40,
    -30,   5,  12,  16,  16,  12,   5, -30,
    -30,   0,  16,  22,  22,  16,   0, -30,
    -30,   5,  16,  22,  22,  16,   5, -30,
    -30,   0,  12,  16,  16,  12,   0, -30,
    -40, -20,   0,   0,   0,   0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
]

PST_BISHOP = [
    -20, -10, -12, -10, -10, -12, -10, -20,
    -10,   8,   0,   0,   0,   0,   8, -10,
    -10,  10,  12,  12,  12,  12,  10, -10,
    -10,   0,  12,  14,  14,  12,   0, -10,
    -10,   6,   8,  14,  14,   8,   6, -10,
    -10,   0,   6,  12,  12,   6,   0, -10,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
]

PST_ROOK = [
      0,   0,   5,  10,  10,   5,   0,   0,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
     -5,   0,   0,   0,   0,   0,   0,  -5,
      8,  12,  12,  12,  12,  12,  12,   8,
      0,   0,   0,   0,   0,   0,   0,   0,
]

# Queen PST: penalize early sorties (rank 1 corners stay home).
PST_QUEEN = [
    -20, -10, -10,  -5,  -5, -10, -10, -20,
    -10,   0,   2,   0,   0,   0,   0, -10,
    -10,   2,   5,   5,   5,   5,   0, -10,
     -5,   0,   5,   5,   5,   5,   0,  -5,
     -5,   0,   5,   5,   5,   5,   0,  -5,
    -10,   0,   5,   5,   5,   5,   0, -10,
    -10,   0,   0,   0,   0,   0,   0, -10,
    -20, -10, -10,  -5,  -5, -10, -10, -20,
]

# King MG: reward castled positions (g1/c1) and home; punish marching the king.
PST_KING_MG = [
     22,  34,  12,   0,   0,  10,  34,  22,
     20,  20,   0,   0,   0,   0,  20,  20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
]

# King EG: centralize.
PST_KING_EG = [
    -50, -30, -30, -30, -30, -30, -30, -50,
    -30, -30,   0,   0,   0,   0, -30, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  30,  40,  40,  30, -10, -30,
    -30, -10,  20,  30,  30,  20, -10, -30,
    -30, -20, -10,   0,   0, -10, -20, -30,
    -50, -40, -30, -20, -20, -30, -40, -50,
]


def _mirror(pst):
    """Return PST mirrored vertically (for black pieces)."""
    out = [0] * 64
    for s in range(64):
        out[s] = pst[sq(file_of(s), 7 - rank_of(s))]
    return out


PST = {
    (PAWN,   WHITE): PST_PAWN,
    (PAWN,   BLACK): _mirror(PST_PAWN),
    (KNIGHT, WHITE): PST_KNIGHT,
    (KNIGHT, BLACK): _mirror(PST_KNIGHT),
    (BISHOP, WHITE): PST_BISHOP,
    (BISHOP, BLACK): _mirror(PST_BISHOP),
    (ROOK,   WHITE): PST_ROOK,
    (ROOK,   BLACK): _mirror(PST_ROOK),
    (QUEEN,  WHITE): PST_QUEEN,
    (QUEEN,  BLACK): _mirror(PST_QUEEN),
}
PST_KING = {
    (WHITE, "mg"): PST_KING_MG,
    (BLACK, "mg"): _mirror(PST_KING_MG),
    (WHITE, "eg"): PST_KING_EG,
    (BLACK, "eg"): _mirror(PST_KING_EG),
}

# Game-phase weighting (24 = full MG; 0 = pure EG).
PHASE_VALUE = {KNIGHT: 1, BISHOP: 1, ROOK: 2, QUEEN: 4}
PHASE_TOTAL = 24


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sliding_mobility(board, frm: int, rays) -> int:
    n = 0
    for ray in rays:
        for t in ray[frm]:
            if board[t] == NO_PIECE:
                n += 1
            else:
                n += 1
                break
    return n


def _knight_mobility(board, frm: int, color: int) -> int:
    n = 0
    for t in KNIGHT_ATTACKS[frm]:
        pc = board[t]
        if pc == NO_PIECE or piece_color(pc) != color:
            n += 1
    return n


# ---------------------------------------------------------------------------
# Evaluation entry point
# ---------------------------------------------------------------------------
def evaluate(pos: Position) -> int:
    board = pos.board
    W = EVAL_WEIGHTS

    mg = 0   # middlegame component
    eg = 0   # endgame component
    phase = 0

    bishop_count = [0, 0]
    rook_squares: list = [[], []]
    pawn_files = [[0] * 8, [0] * 8]
    pawn_squares: list = [[], []]
    has_queen = [False, False]

    # First pass: material + PST + structural collection.
    for s in range(64):
        pc = board[s]
        if pc == NO_PIECE:
            continue
        pt = piece_type(pc)
        c = piece_color(pc)
        sign = 1 if c == WHITE else -1

        if pt == KING:
            mg += sign * PST_KING[(c, "mg")][s]
            eg += sign * PST_KING[(c, "eg")][s]
            continue

        val = MATERIAL[pt]
        mg += sign * val
        eg += sign * val
        pst_val = PST[(pt, c)][s]
        mg += sign * pst_val
        eg += sign * pst_val

        if pt in PHASE_VALUE:
            phase += PHASE_VALUE[pt]
        if pt == BISHOP:
            bishop_count[c] += 1
        elif pt == ROOK:
            rook_squares[c].append(s)
        elif pt == QUEEN:
            has_queen[c] = True
        elif pt == PAWN:
            pawn_files[c][file_of(s)] += 1
            pawn_squares[c].append((file_of(s), rank_of(s)))

    # Bishop pair
    bp = W["bishop_pair"]
    if bishop_count[WHITE] >= 2:
        mg += bp; eg += bp
    if bishop_count[BLACK] >= 2:
        mg -= bp; eg -= bp

    # Pawn structure: doubled + isolated
    dbl = W["doubled_pawn"]
    iso = W["isolated_pawn"]
    for c in (WHITE, BLACK):
        sign = 1 if c == WHITE else -1
        files = pawn_files[c]
        for f in range(8):
            if files[f] >= 2:
                pen = dbl * (files[f] - 1)
                mg += sign * pen; eg += sign * pen
            if files[f] >= 1:
                left  = files[f - 1] if f > 0 else 0
                right = files[f + 1] if f < 7 else 0
                if left == 0 and right == 0:
                    mg += sign * iso; eg += sign * iso

    # Passed pawns
    passed_bonus = W["passed_pawn"]
    eg_scale = W["passed_eg_scale"]
    for c in (WHITE, BLACK):
        sign = 1 if c == WHITE else -1
        opp_pawns = pawn_squares[c ^ 1]
        for (f, r) in pawn_squares[c]:
            blocked = False
            for (of, orank) in opp_pawns:
                if abs(of - f) > 1:
                    continue
                if c == WHITE and orank > r:
                    blocked = True; break
                if c == BLACK and orank < r:
                    blocked = True; break
            if not blocked:
                rel_rank = r if c == WHITE else 7 - r
                b = passed_bonus[rel_rank]
                mg += sign * b
                eg += sign * int(b * eg_scale)

    # Rook on open / semi-open file
    rook_open = W["rook_open_file"]
    rook_semi = W["rook_semi_open"]
    for c in (WHITE, BLACK):
        sign = 1 if c == WHITE else -1
        for rs in rook_squares[c]:
            f = file_of(rs)
            own = pawn_files[c][f]
            their = pawn_files[c ^ 1][f]
            if own == 0 and their == 0:
                mg += sign * rook_open; eg += sign * rook_open
            elif own == 0:
                mg += sign * rook_semi; eg += sign * rook_semi

    # Mobility (knights + sliding pieces). Pawns/king skipped.
    mob_n = W["mobility_knight"]
    mob_b = W["mobility_bishop"]
    mob_r = W["mobility_rook"]
    mob_q = W["mobility_queen"]
    for s in range(64):
        pc = board[s]
        if pc == NO_PIECE:
            continue
        pt = piece_type(pc); c = piece_color(pc)
        sign = 1 if c == WHITE else -1
        if pt == KNIGHT:
            m = _knight_mobility(board, s, c)
            mg += sign * m * mob_n; eg += sign * m * mob_n
        elif pt == BISHOP:
            m = _sliding_mobility(board, s, BISHOP_RAYS)
            mg += sign * m * mob_b; eg += sign * m * mob_b
        elif pt == ROOK:
            m = _sliding_mobility(board, s, ROOK_RAYS)
            mg += sign * m * mob_r; eg += sign * m * mob_r
        elif pt == QUEEN:
            m = (_sliding_mobility(board, s, ROOK_RAYS) +
                 _sliding_mobility(board, s, BISHOP_RAYS))
            mg += sign * m * mob_q; eg += sign * m * mob_q

    # King safety: only meaningful in middlegame (multiplied by phase factor).
    shield_w = W["king_shield_pawn"]
    attacker_w = W["king_attacker"]
    open_w = W["king_open_file"]
    for c in (WHITE, BLACK):
        sign = 1 if c == WHITE else -1
        ks = pos.king_sq[c]
        if ks < 0:
            continue
        kf = file_of(ks)
        kr = rank_of(ks)

        # Shield: pawns directly in front of (and adjacent to) the king.
        own_pawn = make_piece(PAWN, c)
        shield_rank = kr + 1 if c == WHITE else kr - 1
        shield_rank2 = kr + 2 if c == WHITE else kr - 2
        shield = 0
        if 0 <= shield_rank < 8:
            for df in (-1, 0, 1):
                nf = kf + df
                if 0 <= nf < 8 and board[sq(nf, shield_rank)] == own_pawn:
                    shield += 1
            if 0 <= shield_rank2 < 8:
                for df in (-1, 0, 1):
                    nf = kf + df
                    if 0 <= nf < 8 and board[sq(nf, shield_rank2)] == own_pawn:
                        shield += 1  # half-bonus is same value; cheap and fine
        mg += sign * shield * shield_w  # EG: skip

        # Open file penalty: no own pawn on king file / adjacent files AND
        # opponent has a heavy piece (queen / rook) on that file.
        opp = c ^ 1
        rook_pc  = make_piece(ROOK,  opp)
        queen_pc = make_piece(QUEEN, opp)
        for df in (-1, 0, 1):
            nf = kf + df
            if not (0 <= nf < 8):
                continue
            if pawn_files[c][nf] == 0:
                # is there an enemy rook or queen on this file?
                threat = False
                for r in range(8):
                    p = board[sq(nf, r)]
                    if p == rook_pc or p == queen_pc:
                        threat = True
                        break
                if threat:
                    mg += sign * open_w

        # Attacker count in king zone (king square + adjacent).
        attackers = 0
        for t in KING_ATTACKS[ks]:
            if pos.attackers_of(t, opp):
                attackers += 1
        if pos.attackers_of(ks, opp):
            attackers += 1
        # Weight attacker penalty more when the enemy queen is on the board.
        scale = 2 if has_queen[opp] else 1
        mg += sign * attackers * attacker_w * scale

    # Tapered eval
    phase = min(phase, PHASE_TOTAL)
    score = (mg * phase + eg * (PHASE_TOTAL - phase)) // PHASE_TOTAL

    # Tempo (from side-to-move POV)
    score += W["tempo"] if pos.side == WHITE else -W["tempo"]

    # Return from STM perspective.
    return score if pos.side == WHITE else -score
