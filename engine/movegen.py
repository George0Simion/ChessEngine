"""Move generation.

Pseudo-legal generation + legality filter (make/unmake & check own king).
This is the simplest correct approach and is fast enough at our scale.

Public API:
    generate_moves(pos)         -> list[int]           legal moves
    generate_captures(pos)      -> list[int]           legal captures (used by qsearch)
    has_legal_move(pos)         -> bool                stalemate/mate detection
"""

from __future__ import annotations
from typing import List

from .types import (
    WHITE, BLACK, NO_PIECE, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING,
    WK_CASTLE, WQ_CASTLE, BK_CASTLE, BQ_CASTLE,
    F_NORMAL, F_CAPTURE, F_DOUBLE_PUSH, F_EP_CAPTURE,
    F_CASTLE_K, F_CASTLE_Q, F_PROMO, F_PROMO_CAPTURE,
    make_piece, piece_type, piece_color, sq, file_of, rank_of,
    encode_move,
)
from .attacks import (
    KNIGHT_ATTACKS, KING_ATTACKS, PAWN_ATTACKS,
    ROOK_RAYS, BISHOP_RAYS,
)
from .board import Position


# Promotion piece types in standard order (Q, R, B, N).
PROMO_PIECES = (QUEEN, ROOK, BISHOP, KNIGHT)


def _pseudo_pawn_moves(pos: Position, frm: int, color: int, out: list) -> None:
    """Append all pseudo-legal pawn moves from `frm`."""
    board = pos.board
    f = file_of(frm)
    r = rank_of(frm)

    if color == WHITE:
        one = frm + 8
        two = frm + 16
        start_rank = 1
        promo_rank = 7
        capture_offsets = ((7, -1), (9, 1))     # (offset, file_delta)
    else:
        one = frm - 8
        two = frm - 16
        start_rank = 6
        promo_rank = 0
        capture_offsets = ((-7, 1), (-9, -1))

    # Single push
    if 0 <= one < 64 and board[one] == NO_PIECE:
        if rank_of(one) == promo_rank:
            for pp in PROMO_PIECES:
                out.append(encode_move(frm, one, pp, F_PROMO))
        else:
            out.append(encode_move(frm, one, 0, F_NORMAL))
            # Double push only if from starting rank and intermediate empty
            if r == start_rank and 0 <= two < 64 and board[two] == NO_PIECE:
                out.append(encode_move(frm, two, 0, F_DOUBLE_PUSH))

    # Captures
    for off, df in capture_offsets:
        nf = f + df
        if not (0 <= nf < 8):
            continue
        t = frm + off
        if not (0 <= t < 64):
            continue
        tgt = board[t]
        if tgt != NO_PIECE and piece_color(tgt) != color:
            if rank_of(t) == promo_rank:
                for pp in PROMO_PIECES:
                    out.append(encode_move(frm, t, pp, F_PROMO_CAPTURE))
            else:
                out.append(encode_move(frm, t, 0, F_CAPTURE))
        elif t == pos.ep and pos.ep != -1:
            # En passant
            out.append(encode_move(frm, t, 0, F_EP_CAPTURE))


def _pseudo_knight_moves(pos: Position, frm: int, color: int, out: list) -> None:
    board = pos.board
    for t in KNIGHT_ATTACKS[frm]:
        tgt = board[t]
        if tgt == NO_PIECE:
            out.append(encode_move(frm, t, 0, F_NORMAL))
        elif piece_color(tgt) != color:
            out.append(encode_move(frm, t, 0, F_CAPTURE))


def _pseudo_king_moves(pos: Position, frm: int, color: int, out: list) -> None:
    board = pos.board
    for t in KING_ATTACKS[frm]:
        tgt = board[t]
        if tgt == NO_PIECE:
            out.append(encode_move(frm, t, 0, F_NORMAL))
        elif piece_color(tgt) != color:
            out.append(encode_move(frm, t, 0, F_CAPTURE))

    # Castling
    if color == WHITE:
        if pos.castling & WK_CASTLE:
            # squares f1, g1 empty and not attacked, e1 not in check, rook on h1
            if board[5] == NO_PIECE and board[6] == NO_PIECE \
                    and not pos.attackers_of(4, BLACK) \
                    and not pos.attackers_of(5, BLACK) \
                    and not pos.attackers_of(6, BLACK):
                out.append(encode_move(4, 6, 0, F_CASTLE_K))
        if pos.castling & WQ_CASTLE:
            # b1, c1, d1 empty; e1, d1, c1 safe
            if board[1] == NO_PIECE and board[2] == NO_PIECE and board[3] == NO_PIECE \
                    and not pos.attackers_of(4, BLACK) \
                    and not pos.attackers_of(3, BLACK) \
                    and not pos.attackers_of(2, BLACK):
                out.append(encode_move(4, 2, 0, F_CASTLE_Q))
    else:
        if pos.castling & BK_CASTLE:
            if board[61] == NO_PIECE and board[62] == NO_PIECE \
                    and not pos.attackers_of(60, WHITE) \
                    and not pos.attackers_of(61, WHITE) \
                    and not pos.attackers_of(62, WHITE):
                out.append(encode_move(60, 62, 0, F_CASTLE_K))
        if pos.castling & BQ_CASTLE:
            if board[57] == NO_PIECE and board[58] == NO_PIECE and board[59] == NO_PIECE \
                    and not pos.attackers_of(60, WHITE) \
                    and not pos.attackers_of(59, WHITE) \
                    and not pos.attackers_of(58, WHITE):
                out.append(encode_move(60, 58, 0, F_CASTLE_Q))


def _slide(pos: Position, frm: int, color: int, rays, out: list) -> None:
    board = pos.board
    for ray in rays:
        for t in ray[frm]:
            tgt = board[t]
            if tgt == NO_PIECE:
                out.append(encode_move(frm, t, 0, F_NORMAL))
            else:
                if piece_color(tgt) != color:
                    out.append(encode_move(frm, t, 0, F_CAPTURE))
                break


def generate_pseudo_legal(pos: Position) -> List[int]:
    out: List[int] = []
    side = pos.side
    board = pos.board
    for s in range(64):
        pc = board[s]
        if pc == NO_PIECE or piece_color(pc) != side:
            continue
        pt = piece_type(pc)
        if pt == PAWN:
            _pseudo_pawn_moves(pos, s, side, out)
        elif pt == KNIGHT:
            _pseudo_knight_moves(pos, s, side, out)
        elif pt == BISHOP:
            _slide(pos, s, side, BISHOP_RAYS, out)
        elif pt == ROOK:
            _slide(pos, s, side, ROOK_RAYS, out)
        elif pt == QUEEN:
            _slide(pos, s, side, BISHOP_RAYS, out)
            _slide(pos, s, side, ROOK_RAYS, out)
        elif pt == KING:
            _pseudo_king_moves(pos, s, side, out)
    return out


def generate_moves(pos: Position) -> List[int]:
    """Fully legal moves."""
    out: List[int] = []
    side = pos.side
    for m in generate_pseudo_legal(pos):
        pos.make_move(m)
        # After our move, it's opponent's turn. We must not have left our king in check.
        if not pos.attackers_of(pos.king_sq[side], side ^ 1):
            out.append(m)
        pos.unmake_move(m)
    return out


def generate_captures(pos: Position) -> List[int]:
    """Legal captures + promotions (used by quiescence search)."""
    out: List[int] = []
    side = pos.side
    for m in generate_pseudo_legal(pos):
        flag = (m >> 15) & 0xF
        # promotions are search-worthy at qsearch (huge swing); captures obviously
        if flag not in (F_CAPTURE, F_EP_CAPTURE, F_PROMO, F_PROMO_CAPTURE):
            continue
        pos.make_move(m)
        if not pos.attackers_of(pos.king_sq[side], side ^ 1):
            out.append(m)
        pos.unmake_move(m)
    return out


def has_legal_move(pos: Position) -> bool:
    side = pos.side
    for m in generate_pseudo_legal(pos):
        pos.make_move(m)
        legal = not pos.attackers_of(pos.king_sq[side], side ^ 1)
        pos.unmake_move(m)
        if legal:
            return True
    return False
