"""Position state: FEN parse/serialize, make/unmake, attack queries."""

from __future__ import annotations
from typing import List, Optional

from .types import (
    WHITE, BLACK, NO_PIECE, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING,
    PIECE_SYMBOLS, SYMBOL_TO_PIECE,
    WK_CASTLE, WQ_CASTLE, BK_CASTLE, BQ_CASTLE,
    F_DOUBLE_PUSH, F_EP_CAPTURE,
    F_CASTLE_K, F_CASTLE_Q, F_PROMO, F_PROMO_CAPTURE,
    make_piece, piece_type, piece_color, sq, file_of, rank_of, square_name,
)
from .attacks import (
    KNIGHT_ATTACKS, KING_ATTACKS, PAWN_ATTACKS,
    ROOK_RAYS, BISHOP_RAYS,
)
from .zobrist import PIECE_KEYS, SIDE_KEY, CASTLE_KEYS, EP_FILE_KEYS


def _build_castle_mask() -> List[int]:
    """Castling rights lost when a given square is touched (moved-from OR captured-to)."""
    m = [0xF] * 64
    m[sq(0, 0)] &= ~WQ_CASTLE
    m[sq(7, 0)] &= ~WK_CASTLE
    m[sq(4, 0)] &= ~(WK_CASTLE | WQ_CASTLE)
    m[sq(0, 7)] &= ~BQ_CASTLE
    m[sq(7, 7)] &= ~BK_CASTLE
    m[sq(4, 7)] &= ~(BK_CASTLE | BQ_CASTLE)
    return m


CASTLE_MASK_FROM_SQ = _build_castle_mask()


class Position:
    """Mutable chess position with make/unmake."""

    __slots__ = (
        "board", "side", "castling", "ep", "halfmove", "fullmove",
        "king_sq", "zobrist", "history", "hash_history", "irreversible_ply",
    )

    def __init__(self):
        self.board: List[int] = [NO_PIECE] * 64
        self.side = WHITE
        self.castling = 0
        self.ep = -1
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = [-1, -1]
        self.zobrist = 0
        self.history: List[tuple] = []
        self.hash_history: List[int] = []
        # Index into hash_history at the last irreversible move (capture / pawn).
        # Threefold can only be matched against entries from that index forward.
        self.irreversible_ply = 0

    # ------------------------------------------------------------------ FEN
    @classmethod
    def from_fen(cls, fen: str) -> "Position":
        p = cls()
        parts = fen.strip().split()
        if len(parts) < 4:
            raise ValueError(f"bad FEN: {fen!r}")
        placement, side, castling, ep = parts[:4]
        halfmove = parts[4] if len(parts) > 4 else "0"
        fullmove = parts[5] if len(parts) > 5 else "1"

        ranks = placement.split("/")
        if len(ranks) != 8:
            raise ValueError(f"bad FEN placement: {placement!r}")
        for ri, row in enumerate(ranks):
            rank = 7 - ri
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                else:
                    if ch not in SYMBOL_TO_PIECE:
                        raise ValueError(f"bad piece char: {ch!r}")
                    pc = SYMBOL_TO_PIECE[ch]
                    s = sq(f, rank)
                    p.board[s] = pc
                    if piece_type(pc) == KING:
                        p.king_sq[piece_color(pc)] = s
                    f += 1
            if f != 8:
                raise ValueError(f"bad rank length: {row!r}")

        p.side = WHITE if side == "w" else BLACK
        p.castling = 0
        if "K" in castling: p.castling |= WK_CASTLE
        if "Q" in castling: p.castling |= WQ_CASTLE
        if "k" in castling: p.castling |= BK_CASTLE
        if "q" in castling: p.castling |= BQ_CASTLE
        if ep == "-":
            p.ep = -1
        else:
            from .types import square_from_name
            p.ep = square_from_name(ep)
        p.halfmove = int(halfmove)
        p.fullmove = int(fullmove)
        p.zobrist = p._compute_zobrist()
        p.hash_history = [p.zobrist]
        p.irreversible_ply = 0
        return p

    def to_fen(self) -> str:
        rows = []
        for ri in range(8):
            rank = 7 - ri
            row = ""
            empty = 0
            for f in range(8):
                pc = self.board[sq(f, rank)]
                if pc == NO_PIECE:
                    empty += 1
                else:
                    if empty:
                        row += str(empty); empty = 0
                    row += PIECE_SYMBOLS[pc]
            if empty:
                row += str(empty)
            rows.append(row)
        placement = "/".join(rows)
        side = "w" if self.side == WHITE else "b"
        castling = ""
        if self.castling & WK_CASTLE: castling += "K"
        if self.castling & WQ_CASTLE: castling += "Q"
        if self.castling & BK_CASTLE: castling += "k"
        if self.castling & BQ_CASTLE: castling += "q"
        castling = castling or "-"
        ep = "-" if self.ep < 0 else square_name(self.ep)
        return f"{placement} {side} {castling} {ep} {self.halfmove} {self.fullmove}"

    # ------------------------------------------------------------------ Hash
    def _compute_zobrist(self) -> int:
        h = 0
        for s in range(64):
            pc = self.board[s]
            if pc != NO_PIECE:
                h ^= PIECE_KEYS[pc][s]
        if self.side == BLACK:
            h ^= SIDE_KEY
        h ^= CASTLE_KEYS[self.castling]
        if self.ep >= 0:
            h ^= EP_FILE_KEYS[file_of(self.ep)]
        return h

    # ------------------------------------------------------------------ Attacks
    def attackers_of(self, target: int, attacker_color: int) -> bool:
        """True iff `target` is attacked by any piece of `attacker_color`."""
        board = self.board

        # Pawn attackers: a square attacked by `attacker_color` pawns equals
        # the squares that the OPPOSITE-color pawn-attack table reaches from
        # `target`. (Pawn attacks are mirrored.)
        opp = WHITE if attacker_color == BLACK else BLACK
        pawn_pc = make_piece(PAWN, attacker_color)
        for s in PAWN_ATTACKS[opp][target]:
            if board[s] == pawn_pc:
                return True

        knight_pc = make_piece(KNIGHT, attacker_color)
        for s in KNIGHT_ATTACKS[target]:
            if board[s] == knight_pc:
                return True

        king_pc = make_piece(KING, attacker_color)
        for s in KING_ATTACKS[target]:
            if board[s] == king_pc:
                return True

        rook_pc   = make_piece(ROOK,   attacker_color)
        queen_pc  = make_piece(QUEEN,  attacker_color)
        bishop_pc = make_piece(BISHOP, attacker_color)
        for ray in ROOK_RAYS:
            for s in ray[target]:
                pc = board[s]
                if pc == NO_PIECE:
                    continue
                if pc == rook_pc or pc == queen_pc:
                    return True
                break
        for ray in BISHOP_RAYS:
            for s in ray[target]:
                pc = board[s]
                if pc == NO_PIECE:
                    continue
                if pc == bishop_pc or pc == queen_pc:
                    return True
                break
        return False

    def in_check(self, color: Optional[int] = None) -> bool:
        if color is None:
            color = self.side
        return self.attackers_of(self.king_sq[color], color ^ 1)

    # ------------------------------------------------------------------ Make / unmake
    def make_move(self, move: int) -> None:
        board = self.board
        frm = move & 0x3F
        to  = (move >> 6) & 0x3F
        promo = (move >> 12) & 0x7
        flag = (move >> 15) & 0xF

        moving = board[frm]
        mover_color = moving & 1
        mt = moving >> 1

        # Locate the captured piece (handled specially for EP).
        if flag == F_EP_CAPTURE:
            cap_sq = to + (-8 if mover_color == WHITE else 8)
            captured = board[cap_sq]
        else:
            cap_sq = to
            captured = board[to]

        # Push undo record with the resolved captured piece.
        self.history.append((
            move, captured, self.castling, self.ep,
            self.halfmove, self.zobrist, self.irreversible_ply,
        ))

        h = self.zobrist
        if self.ep >= 0:
            h ^= EP_FILE_KEYS[file_of(self.ep)]
        h ^= CASTLE_KEYS[self.castling]

        # Pick up the moving piece.
        board[frm] = NO_PIECE
        h ^= PIECE_KEYS[moving][frm]

        # Remove the captured piece (if any).
        if captured != NO_PIECE:
            board[cap_sq] = NO_PIECE
            h ^= PIECE_KEYS[captured][cap_sq]

        # Place the moving (or promoted) piece on `to`.
        if flag == F_PROMO or flag == F_PROMO_CAPTURE:
            new_piece = make_piece(promo, mover_color)
            board[to] = new_piece
            h ^= PIECE_KEYS[new_piece][to]
        else:
            board[to] = moving
            h ^= PIECE_KEYS[moving][to]

        # Castling rook move.
        if flag == F_CASTLE_K:
            rk_from = sq(7, rank_of(to))
            rk_to   = sq(5, rank_of(to))
            rk_pc   = board[rk_from]
            board[rk_from] = NO_PIECE
            board[rk_to]   = rk_pc
            h ^= PIECE_KEYS[rk_pc][rk_from]
            h ^= PIECE_KEYS[rk_pc][rk_to]
        elif flag == F_CASTLE_Q:
            rk_from = sq(0, rank_of(to))
            rk_to   = sq(3, rank_of(to))
            rk_pc   = board[rk_from]
            board[rk_from] = NO_PIECE
            board[rk_to]   = rk_pc
            h ^= PIECE_KEYS[rk_pc][rk_from]
            h ^= PIECE_KEYS[rk_pc][rk_to]

        if mt == KING:
            self.king_sq[mover_color] = to

        # Castling rights via square mask.
        self.castling &= CASTLE_MASK_FROM_SQ[frm]
        self.castling &= CASTLE_MASK_FROM_SQ[to]
        h ^= CASTLE_KEYS[self.castling]

        # EP target: only set when an enemy pawn could ACTUALLY capture
        # (keeps the hash and rep-detection sharper).
        new_ep = -1
        if flag == F_DOUBLE_PUSH:
            ep_sq = (frm + to) >> 1
            enemy_pawn = make_piece(PAWN, mover_color ^ 1)
            f = file_of(to)
            if (f > 0 and board[to - 1] == enemy_pawn) or \
               (f < 7 and board[to + 1] == enemy_pawn):
                new_ep = ep_sq
        self.ep = new_ep
        if new_ep >= 0:
            h ^= EP_FILE_KEYS[file_of(new_ep)]

        # Halfmove clock + irreversible-ply marker.
        irreversible = (mt == PAWN) or (captured != NO_PIECE)
        if irreversible:
            self.halfmove = 0
        else:
            self.halfmove += 1

        if self.side == BLACK:
            self.fullmove += 1
        self.side ^= 1
        h ^= SIDE_KEY

        self.zobrist = h
        self.hash_history.append(h)
        if irreversible:
            self.irreversible_ply = len(self.hash_history) - 1

    def unmake_move(self, move: int) -> None:
        _ = move  # arg accepted for symmetry; the actual move comes from history
        rec = self.history.pop()
        m, captured, castling, ep, halfmove, zob, irr_ply = rec
        frm = m & 0x3F
        to  = (m >> 6) & 0x3F
        flag = (m >> 15) & 0xF

        # Flip side back first.
        self.side ^= 1
        if self.side == BLACK:
            self.fullmove -= 1

        board = self.board

        # Determine mover at the post-move position.
        if flag == F_PROMO or flag == F_PROMO_CAPTURE:
            mover = make_piece(PAWN, self.side)
        else:
            mover = board[to]
        board[frm] = mover
        board[to]  = NO_PIECE

        # Restore captured piece (if any) on its real capture square.
        if captured != NO_PIECE:
            if flag == F_EP_CAPTURE:
                cap_sq = to + (-8 if self.side == WHITE else 8)
                board[cap_sq] = captured
            else:
                board[to] = captured

        if flag == F_CASTLE_K:
            rk_from = sq(7, rank_of(to))
            rk_to   = sq(5, rank_of(to))
            board[rk_from] = board[rk_to]
            board[rk_to] = NO_PIECE
        elif flag == F_CASTLE_Q:
            rk_from = sq(0, rank_of(to))
            rk_to   = sq(3, rank_of(to))
            board[rk_from] = board[rk_to]
            board[rk_to] = NO_PIECE

        if (mover >> 1) == KING:
            self.king_sq[self.side] = frm

        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.zobrist = zob
        self.hash_history.pop()
        self.irreversible_ply = irr_ply

    # ------------------------------------------------------------------ Null move
    def make_null(self) -> None:
        self.history.append((
            0, NO_PIECE, self.castling, self.ep,
            self.halfmove, self.zobrist, self.irreversible_ply,
        ))
        h = self.zobrist
        if self.ep >= 0:
            h ^= EP_FILE_KEYS[file_of(self.ep)]
            self.ep = -1
        h ^= SIDE_KEY
        self.side ^= 1
        self.halfmove += 1
        self.zobrist = h
        self.hash_history.append(h)
        self.irreversible_ply = len(self.hash_history) - 1

    def unmake_null(self) -> None:
        rec = self.history.pop()
        _, _, castling, ep, halfmove, zob, irr_ply = rec
        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.zobrist = zob
        self.side ^= 1
        self.hash_history.pop()
        self.irreversible_ply = irr_ply

    # ------------------------------------------------------------------ Draws
    def is_threefold(self) -> bool:
        """Threefold repetition: only positions since the last irreversible
        move can match (faster scan)."""
        h = self.zobrist
        count = 0
        hh = self.hash_history
        # Same-side-to-move repetitions occur every 2 plies, but we just count
        # exact hash matches which already include side-to-move.
        for i in range(self.irreversible_ply, len(hh)):
            if hh[i] == h:
                count += 1
                if count >= 3:
                    return True
        return False

    def is_fifty_move(self) -> bool:
        return self.halfmove >= 100

    def insufficient_material(self) -> bool:
        # K vs K, K+(N|B) vs K, K+B vs K+B with same-color bishops.
        minor = [0, 0]   # minor pieces per color
        bishop_sq = [-1, -1]
        for s in range(64):
            pc = self.board[s]
            if pc == NO_PIECE:
                continue
            pt = piece_type(pc); c = piece_color(pc)
            if pt == PAWN or pt == ROOK or pt == QUEEN:
                return False
            if pt == BISHOP:
                minor[c] += 1
                bishop_sq[c] = s
            elif pt == KNIGHT:
                minor[c] += 1
        # K+0 vs K+0
        if minor[WHITE] == 0 and minor[BLACK] == 0:
            return True
        # K + single minor vs K
        if minor[WHITE] <= 1 and minor[BLACK] == 0:
            return True
        if minor[BLACK] <= 1 and minor[WHITE] == 0:
            return True
        return False

    def is_drawn(self) -> bool:
        return (self.is_fifty_move() or self.is_threefold()
                or self.insufficient_material())

    # ------------------------------------------------------------------ Debug
    def __str__(self) -> str:
        rows = []
        for ri in range(8):
            rank = 7 - ri
            row = []
            for f in range(8):
                row.append(PIECE_SYMBOLS[self.board[sq(f, rank)]])
            rows.append(" ".join(row))
        side = "white" if self.side == WHITE else "black"
        return "\n".join(rows) + f"\n  {side} to move"
