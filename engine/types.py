"""Core constants, square helpers and move encoding.

Squares: a1=0, b1=1, ..., h1=7, a2=8, ..., h8=63
Pieces are encoded as a packed integer = (piece_type * 2 + color), 0 = empty.
Color: 0 = White, 1 = Black.
Piece type: 1=P, 2=N, 3=B, 4=R, 5=Q, 6=K.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Colors / piece types
# ---------------------------------------------------------------------------
WHITE = 0
BLACK = 1

PAWN   = 1
KNIGHT = 2
BISHOP = 3
ROOK   = 4
QUEEN  = 5
KING   = 6

PIECE_TYPES = (PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING)

NO_PIECE = 0
WP = (PAWN   << 1) | WHITE
WN = (KNIGHT << 1) | WHITE
WB = (BISHOP << 1) | WHITE
WR = (ROOK   << 1) | WHITE
WQ = (QUEEN  << 1) | WHITE
WK = (KING   << 1) | WHITE
BP = (PAWN   << 1) | BLACK
BN = (KNIGHT << 1) | BLACK
BB = (BISHOP << 1) | BLACK
BR = (ROOK   << 1) | BLACK
BQ = (QUEEN  << 1) | BLACK
BK = (KING   << 1) | BLACK

ALL_PIECES = (WP, WN, WB, WR, WQ, WK, BP, BN, BB, BR, BQ, BK)

PIECE_SYMBOLS = {
    NO_PIECE: ".",
    WP: "P", WN: "N", WB: "B", WR: "R", WQ: "Q", WK: "K",
    BP: "p", BN: "n", BB: "b", BR: "r", BQ: "q", BK: "k",
}
SYMBOL_TO_PIECE = {v: k for k, v in PIECE_SYMBOLS.items() if k != NO_PIECE}

def make_piece(pt: int, color: int) -> int:
    return (pt << 1) | color

def piece_type(p: int) -> int:
    return p >> 1

def piece_color(p: int) -> int:
    return p & 1

# ---------------------------------------------------------------------------
# Squares
# ---------------------------------------------------------------------------
FILES = "abcdefgh"
RANKS = "12345678"

def sq(file: int, rank: int) -> int:
    return rank * 8 + file

def file_of(s: int) -> int:
    return s & 7

def rank_of(s: int) -> int:
    return s >> 3

def square_name(s: int) -> str:
    return FILES[file_of(s)] + RANKS[rank_of(s)]

def square_from_name(name: str) -> int:
    name = name.strip().lower()
    if len(name) != 2 or name[0] not in FILES or name[1] not in RANKS:
        raise ValueError(f"bad square: {name!r}")
    return sq(FILES.index(name[0]), RANKS.index(name[1]))

# ---------------------------------------------------------------------------
# Castling rights (bitmask)
# ---------------------------------------------------------------------------
WK_CASTLE = 1 << 0
WQ_CASTLE = 1 << 1
BK_CASTLE = 1 << 2
BQ_CASTLE = 1 << 3

# ---------------------------------------------------------------------------
# Move encoding (int):
#   bits 0-5   : from (0-63)
#   bits 6-11  : to   (0-63)
#   bits 12-14 : promotion piece type (0 = none, else 2..5 for N/B/R/Q)
#   bits 15-18 : flags
#
# Flags:
#   0 NORMAL
#   1 CAPTURE
#   2 DOUBLE_PUSH
#   3 EP_CAPTURE
#   4 CASTLE_K
#   5 CASTLE_Q
#   6 PROMOTION
#   7 PROMOTION_CAPTURE
# ---------------------------------------------------------------------------
F_NORMAL            = 0
F_CAPTURE           = 1
F_DOUBLE_PUSH       = 2
F_EP_CAPTURE        = 3
F_CASTLE_K          = 4
F_CASTLE_Q          = 5
F_PROMO             = 6
F_PROMO_CAPTURE     = 7

def encode_move(frm: int, to: int, promo: int = 0, flag: int = F_NORMAL) -> int:
    return frm | (to << 6) | (promo << 12) | (flag << 15)

def move_from(m: int) -> int:    return m & 0x3F
def move_to(m: int) -> int:      return (m >> 6) & 0x3F
def move_promo(m: int) -> int:   return (m >> 12) & 0x7
def move_flag(m: int) -> int:    return (m >> 15) & 0xF

def is_capture(m: int) -> bool:
    f = move_flag(m)
    return f == F_CAPTURE or f == F_EP_CAPTURE or f == F_PROMO_CAPTURE

def is_promotion(m: int) -> bool:
    f = move_flag(m)
    return f == F_PROMO or f == F_PROMO_CAPTURE

NO_MOVE = 0

def move_to_uci(m: int) -> str:
    frm = move_from(m)
    to  = move_to(m)
    promo = move_promo(m)
    s = square_name(frm) + square_name(to)
    if is_promotion(m):
        s += "nbrq"[promo - KNIGHT]
    return s

# ---------------------------------------------------------------------------
# Starting position
# ---------------------------------------------------------------------------
FEN_START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# Material values used in eval AND in move ordering.
PIECE_VALUE = {
    PAWN:   100,
    KNIGHT: 320,
    BISHOP: 330,
    ROOK:   500,
    QUEEN:  900,
    KING:   20000,   # huge so king "captures" stand out (won't happen in legal play)
}

# A mate score that fits comfortably in eval space.
MATE = 30000
MATE_IN_MAX = MATE - 1000   # threshold to detect "mate-in-N" scores
INF = 1 << 24
