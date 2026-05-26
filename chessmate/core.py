from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


FILES = "abcdefgh"
RANKS = "12345678"

WHITE = "white"
BLACK = "black"
COLORS = {WHITE, BLACK}

PAWN = "pawn"
KNIGHT = "knight"
BISHOP = "bishop"
ROOK = "rook"
QUEEN = "queen"
KING = "king"

PIECE_SYMBOLS = {
    (WHITE, KING): "\u2654",
    (WHITE, QUEEN): "\u2655",
    (WHITE, ROOK): "\u2656",
    (WHITE, BISHOP): "\u2657",
    (WHITE, KNIGHT): "\u2658",
    (WHITE, PAWN): "\u2659",
    (BLACK, KING): "\u265A",
    (BLACK, QUEEN): "\u265B",
    (BLACK, ROOK): "\u265C",
    (BLACK, BISHOP): "\u265D",
    (BLACK, KNIGHT): "\u265E",
    (BLACK, PAWN): "\u265F",
}

PIECE_LABELS = {
    PAWN: "pion",
    KNIGHT: "cal",
    BISHOP: "nebun",
    ROOK: "turn",
    QUEEN: "dama",
    KING: "rege",
}

# SAN piece letters (English, standard).
SAN_LETTERS = {
    KNIGHT: "N",
    BISHOP: "B",
    ROOK: "R",
    QUEEN: "Q",
    KING: "K",
}

PROMOTION_PIECES = {QUEEN, ROOK, BISHOP, KNIGHT}

# Centipawn-ish material values, used by draw detection and the engine.
# Kings are intentionally NOT counted in material — used only for endgame logic.
PIECE_VALUES = {PAWN: 1, KNIGHT: 3, BISHOP: 3, ROOK: 5, QUEEN: 9, KING: 0}


class InvalidMoveError(ValueError):
    """Raised when a move or square selection is invalid."""


@dataclass(frozen=True)
class Piece:
    color: str
    kind: str

    @property
    def symbol(self) -> str:
        return PIECE_SYMBOLS[(self.color, self.kind)]

    def to_dict(self) -> dict[str, str]:
        return {
            "color": self.color,
            "kind": self.kind,
            "label": PIECE_LABELS[self.kind],
            "symbol": self.symbol,
        }


@dataclass
class MoveRecord:
    """Snapshot of a single move; powers the history panel and undo."""

    number: int
    color: str
    origin: str
    destination: str
    piece_kind: str
    captured_kind: Optional[str]
    captured_color: Optional[str]
    san: str
    is_check: bool
    is_checkmate: bool
    is_stalemate: bool
    castling: Optional[str]  # "K" / "Q" / None
    en_passant_capture_square: Optional[str]
    promotion_kind: Optional[str]
    prev_castling_rights: dict[str, dict[str, bool]] = field(default_factory=dict)
    prev_en_passant_target: Optional[str] = None
    prev_halfmove_clock: int = 0
    prev_position_counts: Optional[dict[str, int]] = None  # for threefold rollback

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "color": self.color,
            "from": self.origin,
            "to": self.destination,
            "pieceKind": self.piece_kind,
            "capturedKind": self.captured_kind,
            "capturedColor": self.captured_color,
            "san": self.san,
            "isCheck": self.is_check,
            "isCheckmate": self.is_checkmate,
            "isStalemate": self.is_stalemate,
            "castling": self.castling,
            "promotionKind": self.promotion_kind,
        }


def opponent(color: str) -> str:
    return BLACK if color == WHITE else WHITE


def normalize_square(square: str) -> str:
    if not isinstance(square, str):
        raise InvalidMoveError("Coordonata trebuie sa fie text.")

    normalized = square.strip().lower()
    if len(normalized) != 2 or normalized[0] not in FILES or normalized[1] not in RANKS:
        raise InvalidMoveError(f"Coordonata invalida: {square!r}.")
    return normalized


def square_to_coords(square: str) -> tuple[int, int]:
    normalized = normalize_square(square)
    return FILES.index(normalized[0]), RANKS.index(normalized[1])


def coords_to_square(file_index: int, rank_index: int) -> str:
    if not is_on_board(file_index, rank_index):
        raise InvalidMoveError("Coordonata este in afara tablei.")
    return f"{FILES[file_index]}{RANKS[rank_index]}"


def is_on_board(file_index: int, rank_index: int) -> bool:
    return 0 <= file_index < 8 and 0 <= rank_index < 8


class ChessGame:
    """Standard chess: full rules, history, check/mate/stalemate, castling, en passant,
    promotion, plus the three draw conditions (insufficient material, 50-move rule,
    threefold repetition).

    The class also exposes:
      - ``all_legal_moves(color)`` for engine integration
      - ``engine_make_move`` / ``engine_undo`` — fast-path move application that
        skips SAN building and end-of-turn status recomputation (used by MCTS).
    """

    def __init__(self) -> None:
        self.board: dict[str, Piece] = {}
        self.turn = WHITE
        self.history: list[MoveRecord] = []
        self.captured: dict[str, list[str]] = {WHITE: [], BLACK: []}
        self.castling_rights: dict[str, dict[str, bool]] = {
            WHITE: {"K": True, "Q": True},
            BLACK: {"K": True, "Q": True},
        }
        self.en_passant_target: Optional[str] = None
        self.halfmove_clock = 0
        # Map from position-hash -> times that exact position has been reached.
        # Used for threefold repetition.
        self.position_counts: dict[str, int] = {}
        # Cached status (computed at end of move()) so that state() does not
        # have to redo _count_legal_moves on the next render.
        self._cached_status: Optional[tuple[str, Optional[str], bool]] = None
        self.reset()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self.board = self._initial_board()
        self.turn = WHITE
        self.history = []
        self.captured = {WHITE: [], BLACK: []}
        self.castling_rights = {
            WHITE: {"K": True, "Q": True},
            BLACK: {"K": True, "Q": True},
        }
        self.en_passant_target = None
        self.halfmove_clock = 0
        self.position_counts = {}
        self._cached_status = None
        # Seed the position counter with the starting position.
        self._bump_position_count()

    def state(self) -> dict[str, object]:
        status, winner, in_check = self._current_status()

        last = self.history[-1] if self.history else None

        return {
            "board": {
                square: piece.to_dict()
                for square, piece in sorted(self.board.items(), key=lambda item: square_sort_key(item[0]))
            },
            "turn": self.turn,
            "turnLabel": self._color_label(self.turn),
            "status": status,
            "winner": winner,
            "winnerLabel": self._color_label(winner) if winner else None,
            "inCheck": in_check,
            "checkSquare": self._find_king(self.turn) if in_check else None,
            "history": [record.to_dict() for record in self.history],
            "captured": {
                WHITE: list(self.captured[WHITE]),
                BLACK: list(self.captured[BLACK]),
            },
            "lastMove": (
                {"from": last.origin, "to": last.destination}
                if last is not None
                else None
            ),
            "canUndo": len(self.history) > 0,
            "moveNumber": (len(self.history) // 2) + 1,
            "halfmoveClock": self.halfmove_clock,
        }

    def piece_at(self, square: str) -> Piece | None:
        return self.board.get(normalize_square(square))

    def legal_moves_for(self, square: str) -> list[str]:
        origin = normalize_square(square)
        piece = self.board.get(origin)
        if piece is None:
            raise InvalidMoveError("Nu exista piesa pe patratul selectat.")
        if piece.color != self.turn:
            raise InvalidMoveError(f"Este randul pieselor {self._color_label(self.turn).lower()}.")

        candidates = self._candidate_moves(origin, piece)
        legal = [target for target in candidates if not self._move_leaves_king_in_check(origin, target)]
        return sorted(legal, key=square_sort_key)

    def all_legal_moves(self, color: Optional[str] = None) -> list[tuple[str, str, Optional[str]]]:
        """Enumerate every legal move available to ``color`` (default: side to move).

        Each entry is ``(origin, destination, promotion)``. For a promotion
        move, four entries are produced (one per promotion piece). For all
        other moves, ``promotion`` is ``None``.

        Used primarily by the engine; it does NOT enforce that ``color`` is the
        side to move (any color can be queried).
        """
        target_color = color or self.turn
        result: list[tuple[str, str, Optional[str]]] = []
        for origin, piece in list(self.board.items()):
            if piece.color != target_color:
                continue
            for destination in self._candidate_moves(origin, piece):
                if self._move_leaves_king_in_check(origin, destination):
                    continue
                if piece.kind == PAWN and self._is_promotion_rank(piece.color, destination):
                    for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                        result.append((origin, destination, promo))
                else:
                    result.append((origin, destination, None))
        return result

    def move(self, origin: str, target: str, *, promotion: Optional[str] = None) -> dict[str, object]:
        source = normalize_square(origin)
        destination = normalize_square(target)

        if source == destination:
            raise InvalidMoveError("Alege un patrat diferit pentru mutare.")

        piece = self.board.get(source)
        if piece is None:
            raise InvalidMoveError("Nu exista piesa pe patratul de pornire.")
        if piece.color != self.turn:
            raise InvalidMoveError(f"Este randul pieselor {self._color_label(self.turn).lower()}.")

        target_piece = self.board.get(destination)
        if target_piece is not None and target_piece.color == piece.color:
            raise InvalidMoveError("Nu poti captura propria piesa.")

        candidates = self._candidate_moves(source, piece)
        if destination not in candidates:
            raise InvalidMoveError("Mutarea nu este valida pentru piesa selectata.")

        if self._move_leaves_king_in_check(source, destination):
            raise InvalidMoveError("Mutarea ar lasa regele in sah.")

        record = self._apply_move(source, destination, piece, target_piece, promotion=promotion)

        # ---- After applying, compute status info that goes into the move record + SAN ----
        in_check_for_next = self.is_in_check(self.turn)
        legal_count = self._count_legal_moves(self.turn)
        is_checkmate = in_check_for_next and legal_count == 0
        is_stalemate = (not in_check_for_next) and legal_count == 0

        san = self._build_san(
            piece=piece,
            source=source,
            destination=destination,
            captured=record.captured_kind is not None,
            castling=record.castling,
            promotion_kind=record.promotion_kind,
            is_check=in_check_for_next,
            is_checkmate=is_checkmate,
        )

        record.san = san
        record.is_check = in_check_for_next and not is_checkmate
        record.is_checkmate = is_checkmate
        record.is_stalemate = is_stalemate
        self.history.append(record)

        # Decide final status — checkmate / stalemate beat draw rules, but if there's no
        # mate/stalemate we still need to honour insufficient material / 50-move / 3-fold.
        if is_checkmate:
            status = "checkmate"
            winner = opponent(self.turn)
        elif is_stalemate:
            status = "stalemate"
            winner = None
        elif self._is_insufficient_material():
            status = "draw_insufficient"
            winner = None
        elif self.halfmove_clock >= 100:  # 50 full moves = 100 plies
            status = "draw_fifty_move"
            winner = None
        elif self._is_threefold_repetition():
            status = "draw_repetition"
            winner = None
        else:
            status = "active"
            winner = None

        self._cached_status = (status, winner, in_check_for_next)
        return self.state()

    def undo(self) -> dict[str, object]:
        if not self.history:
            raise InvalidMoveError("Nu exista mutari de anulat.")

        record = self.history.pop()
        self._revert_move(record)
        # Invalidate cache so the next state() recomputes from scratch.
        self._cached_status = None
        return self.state()

    # ------------------------------------------------------------------
    # Engine fast path (used by MCTS / random bot)
    # ------------------------------------------------------------------

    def engine_make_move(
        self,
        origin: str,
        destination: str,
        promotion: Optional[str] = None,
    ) -> MoveRecord:
        """Apply a known-legal move quickly: no SAN, no checkmate/draw scan.

        Returns the ``MoveRecord`` so it can be undone via ``engine_undo``.
        The move IS validated for legality so that engine bugs surface
        early — but the expensive end-of-turn status work is skipped.
        """
        source = normalize_square(origin)
        target = normalize_square(destination)

        piece = self.board.get(source)
        if piece is None or piece.color != self.turn:
            raise InvalidMoveError("Mutare invalida pentru engine.")

        target_piece = self.board.get(target)
        if target_piece is not None and target_piece.color == piece.color:
            raise InvalidMoveError("Mutare invalida pentru engine.")

        record = self._apply_move(source, target, piece, target_piece, promotion=promotion)
        self.history.append(record)
        self._cached_status = None
        return record

    def engine_undo(self) -> None:
        """Undo the most recent ``engine_make_move`` (or ``move``)."""
        if not self.history:
            return
        record = self.history.pop()
        self._revert_move(record)
        self._cached_status = None

    # ------------------------------------------------------------------
    # Move application & reversal (shared by ``move`` and engine fast path)
    # ------------------------------------------------------------------

    def _apply_move(
        self,
        source: str,
        destination: str,
        piece: Piece,
        target_piece: Optional[Piece],
        *,
        promotion: Optional[str],
    ) -> MoveRecord:
        """Mutate state to reflect a move; build a MoveRecord for later undo.

        Does NOT compute SAN, check/mate status, or final draw flags — callers
        handle those. Position-count bookkeeping for threefold IS performed
        because it must stay consistent across move/undo regardless of caller.
        """
        # ---- detect special moves ----
        is_castling: Optional[str] = None
        en_passant_capture_square: Optional[str] = None
        promotion_kind: Optional[str] = None

        if piece.kind == KING and abs(square_to_coords(destination)[0] - square_to_coords(source)[0]) == 2:
            is_castling = "K" if FILES.index(destination[0]) == 6 else "Q"

        if (
            piece.kind == PAWN
            and self.en_passant_target == destination
            and target_piece is None
            and source[0] != destination[0]
        ):
            en_passant_capture_square = destination[0] + source[1]

        if piece.kind == PAWN and self._is_promotion_rank(piece.color, destination):
            requested = (promotion or QUEEN).strip().lower()
            if requested not in PROMOTION_PIECES:
                raise InvalidMoveError(f"Piesa de promovare invalida: {promotion!r}.")
            promotion_kind = requested

        # Snapshot for undo BEFORE we mutate state.
        prev_castling_rights = {
            WHITE: dict(self.castling_rights[WHITE]),
            BLACK: dict(self.castling_rights[BLACK]),
        }
        prev_en_passant_target = self.en_passant_target
        prev_halfmove_clock = self.halfmove_clock
        prev_position_counts = dict(self.position_counts)

        # ---- apply ----
        captured_kind: Optional[str] = None
        captured_color: Optional[str] = None

        if en_passant_capture_square is not None:
            captured_pawn = self.board.pop(en_passant_capture_square)
            captured_kind = captured_pawn.kind
            captured_color = captured_pawn.color
            self.captured[captured_color].append(captured_kind)
        elif target_piece is not None:
            captured_kind = target_piece.kind
            captured_color = target_piece.color
            self.captured[captured_color].append(captured_kind)

        moved_piece = piece if promotion_kind is None else Piece(piece.color, promotion_kind)
        self.board[destination] = moved_piece
        del self.board[source]

        if is_castling is not None:
            rank = source[1]
            if is_castling == "K":
                rook_from, rook_to = "h" + rank, "f" + rank
            else:
                rook_from, rook_to = "a" + rank, "d" + rank
            self.board[rook_to] = self.board.pop(rook_from)

        self._update_castling_rights_after_move(piece, source, destination)

        if piece.kind == PAWN and abs(square_to_coords(destination)[1] - square_to_coords(source)[1]) == 2:
            mid_rank_index = (square_to_coords(source)[1] + square_to_coords(destination)[1]) // 2
            self.en_passant_target = coords_to_square(square_to_coords(source)[0], mid_rank_index)
        else:
            self.en_passant_target = None

        if piece.kind == PAWN or captured_kind is not None:
            self.halfmove_clock = 0
            # Pawn moves and captures are irreversible -> reset position tracking.
            self.position_counts = {}
        else:
            self.halfmove_clock = prev_halfmove_clock + 1

        self.turn = opponent(self.turn)
        self._bump_position_count()

        return MoveRecord(
            number=(len(self.history) // 2) + 1,
            color=piece.color,
            origin=source,
            destination=destination,
            piece_kind=piece.kind,
            captured_kind=captured_kind,
            captured_color=captured_color,
            san="",                # set by caller if needed
            is_check=False,        # set by caller if needed
            is_checkmate=False,    # set by caller if needed
            is_stalemate=False,    # set by caller if needed
            castling=is_castling,
            en_passant_capture_square=en_passant_capture_square,
            promotion_kind=promotion_kind,
            prev_castling_rights=prev_castling_rights,
            prev_en_passant_target=prev_en_passant_target,
            prev_halfmove_clock=prev_halfmove_clock,
            prev_position_counts=prev_position_counts,
        )

    def _revert_move(self, record: MoveRecord) -> None:
        """Roll back the changes produced by ``_apply_move`` for ``record``."""
        self.turn = record.color

        # Put the original (un-promoted) piece back on its source square.
        self.board[record.origin] = Piece(record.color, record.piece_kind)
        if record.destination in self.board:
            del self.board[record.destination]

        # Reverse castling rook movement.
        if record.castling is not None:
            rank = record.origin[1]
            if record.castling == "K":
                rook_from, rook_to = "f" + rank, "h" + rank
            else:
                rook_from, rook_to = "d" + rank, "a" + rank
            if rook_from in self.board:
                self.board[rook_to] = self.board.pop(rook_from)

        # Restore captured piece.
        if record.captured_kind is not None:
            captured_piece = Piece(record.captured_color, record.captured_kind)
            if record.en_passant_capture_square is not None:
                self.board[record.en_passant_capture_square] = captured_piece
            else:
                self.board[record.destination] = captured_piece
            if self.captured[record.captured_color]:
                self.captured[record.captured_color].pop()

        self.castling_rights = {
            WHITE: dict(record.prev_castling_rights.get(WHITE, {"K": True, "Q": True})),
            BLACK: dict(record.prev_castling_rights.get(BLACK, {"K": True, "Q": True})),
        }
        self.en_passant_target = record.prev_en_passant_target
        self.halfmove_clock = record.prev_halfmove_clock
        self.position_counts = (
            dict(record.prev_position_counts) if record.prev_position_counts is not None else {}
        )

    # ------------------------------------------------------------------
    # Move generation
    # ------------------------------------------------------------------

    def _candidate_moves(self, origin: str, piece: Piece) -> list[str]:
        file_index, rank_index = square_to_coords(origin)

        if piece.kind == PAWN:
            return self._pawn_moves(file_index, rank_index, piece.color)
        if piece.kind == KNIGHT:
            return self._jump_moves(file_index, rank_index, piece.color, [
                (-2, -1), (-2, 1), (-1, -2), (-1, 2),
                (1, -2), (1, 2), (2, -1), (2, 1),
            ])
        if piece.kind == KING:
            moves = self._jump_moves(file_index, rank_index, piece.color, [
                (-1, -1), (-1, 0), (-1, 1), (0, -1),
                (0, 1), (1, -1), (1, 0), (1, 1),
            ])
            moves.extend(self._castling_moves(piece.color))
            return moves
        if piece.kind == BISHOP:
            return self._sliding_moves(file_index, rank_index, piece.color, [(-1, -1), (-1, 1), (1, -1), (1, 1)])
        if piece.kind == ROOK:
            return self._sliding_moves(file_index, rank_index, piece.color, [(-1, 0), (1, 0), (0, -1), (0, 1)])
        if piece.kind == QUEEN:
            return self._sliding_moves(file_index, rank_index, piece.color, [
                (-1, -1), (-1, 1), (1, -1), (1, 1),
                (-1, 0), (1, 0), (0, -1), (0, 1),
            ])

        raise InvalidMoveError(f"Tip de piesa necunoscut: {piece.kind}.")

    def _pawn_moves(self, file_index: int, rank_index: int, color: str) -> list[str]:
        direction = 1 if color == WHITE else -1
        start_rank = 1 if color == WHITE else 6
        moves: list[str] = []

        one_rank = rank_index + direction
        if is_on_board(file_index, one_rank):
            one_square = coords_to_square(file_index, one_rank)
            if one_square not in self.board:
                moves.append(one_square)

                two_rank = rank_index + (2 * direction)
                if rank_index == start_rank and is_on_board(file_index, two_rank):
                    two_square = coords_to_square(file_index, two_rank)
                    if two_square not in self.board:
                        moves.append(two_square)

        for file_delta in (-1, 1):
            target_file = file_index + file_delta
            target_rank = rank_index + direction
            if not is_on_board(target_file, target_rank):
                continue

            target_square = coords_to_square(target_file, target_rank)
            target_piece = self.board.get(target_square)
            if target_piece is not None and target_piece.color != color:
                moves.append(target_square)
            elif target_square == self.en_passant_target:
                moves.append(target_square)

        return moves

    def _jump_moves(
        self,
        file_index: int,
        rank_index: int,
        color: str,
        offsets: Iterable[tuple[int, int]],
    ) -> list[str]:
        moves: list[str] = []
        for file_delta, rank_delta in offsets:
            target_file = file_index + file_delta
            target_rank = rank_index + rank_delta
            if not is_on_board(target_file, target_rank):
                continue

            target_square = coords_to_square(target_file, target_rank)
            target_piece = self.board.get(target_square)
            if target_piece is None or target_piece.color != color:
                moves.append(target_square)
        return moves

    def _sliding_moves(
        self,
        file_index: int,
        rank_index: int,
        color: str,
        directions: Iterable[tuple[int, int]],
    ) -> list[str]:
        moves: list[str] = []
        for file_delta, rank_delta in directions:
            target_file = file_index + file_delta
            target_rank = rank_index + rank_delta

            while is_on_board(target_file, target_rank):
                target_square = coords_to_square(target_file, target_rank)
                target_piece = self.board.get(target_square)
                if target_piece is None:
                    moves.append(target_square)
                else:
                    if target_piece.color != color:
                        moves.append(target_square)
                    break

                target_file += file_delta
                target_rank += rank_delta

        return moves

    def _castling_moves(self, color: str) -> list[str]:
        moves: list[str] = []
        rank = "1" if color == WHITE else "8"
        king_square = "e" + rank

        if self.board.get(king_square) != Piece(color, KING):
            return moves
        if self.is_in_check(color):
            return moves

        rights = self.castling_rights[color]
        if rights.get("K") and self.board.get("h" + rank) == Piece(color, ROOK):
            if (
                "f" + rank not in self.board
                and "g" + rank not in self.board
                and not self._square_attacked_by(opponent(color), "f" + rank)
                and not self._square_attacked_by(opponent(color), "g" + rank)
            ):
                moves.append("g" + rank)
        if rights.get("Q") and self.board.get("a" + rank) == Piece(color, ROOK):
            if (
                "b" + rank not in self.board
                and "c" + rank not in self.board
                and "d" + rank not in self.board
                and not self._square_attacked_by(opponent(color), "d" + rank)
                and not self._square_attacked_by(opponent(color), "c" + rank)
            ):
                moves.append("c" + rank)

        return moves

    def _update_castling_rights_after_move(self, piece: Piece, source: str, destination: str) -> None:
        if piece.kind == KING:
            self.castling_rights[piece.color] = {"K": False, "Q": False}
        if piece.kind == ROOK:
            if source == "a1":
                self.castling_rights[WHITE]["Q"] = False
            elif source == "h1":
                self.castling_rights[WHITE]["K"] = False
            elif source == "a8":
                self.castling_rights[BLACK]["Q"] = False
            elif source == "h8":
                self.castling_rights[BLACK]["K"] = False
        if destination == "a1":
            self.castling_rights[WHITE]["Q"] = False
        elif destination == "h1":
            self.castling_rights[WHITE]["K"] = False
        elif destination == "a8":
            self.castling_rights[BLACK]["Q"] = False
        elif destination == "h8":
            self.castling_rights[BLACK]["K"] = False

    # ------------------------------------------------------------------
    # Check / attack detection
    # ------------------------------------------------------------------

    def is_in_check(self, color: str) -> bool:
        king_square = self._find_king(color)
        if king_square is None:
            return False
        return self._square_attacked_by(opponent(color), king_square)

    def _find_king(self, color: str) -> Optional[str]:
        for square, piece in self.board.items():
            if piece.color == color and piece.kind == KING:
                return square
        return None

    def _square_attacked_by(self, attacker_color: str, square: str) -> bool:
        target_file, target_rank = square_to_coords(square)

        # Pawn attacks (a pawn attacks diagonally forward, so to check whether
        # an attacker's pawn covers `square`, we look back one rank from the
        # attacker's perspective).
        pawn_direction = 1 if attacker_color == WHITE else -1
        for file_delta in (-1, 1):
            from_file = target_file + file_delta
            from_rank = target_rank - pawn_direction
            if is_on_board(from_file, from_rank):
                p = self.board.get(coords_to_square(from_file, from_rank))
                if p is not None and p.color == attacker_color and p.kind == PAWN:
                    return True

        # Knight attacks
        for df, dr in [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]:
            f = target_file + df
            r = target_rank + dr
            if is_on_board(f, r):
                p = self.board.get(coords_to_square(f, r))
                if p is not None and p.color == attacker_color and p.kind == KNIGHT:
                    return True

        # King adjacency
        for df in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if df == 0 and dr == 0:
                    continue
                f = target_file + df
                r = target_rank + dr
                if is_on_board(f, r):
                    p = self.board.get(coords_to_square(f, r))
                    if p is not None and p.color == attacker_color and p.kind == KING:
                        return True

        # Sliding attacks
        directions_orth = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        directions_diag = [(-1, -1), (-1, 1), (1, -1), (1, 1)]

        for df, dr in directions_orth:
            f, r = target_file + df, target_rank + dr
            while is_on_board(f, r):
                p = self.board.get(coords_to_square(f, r))
                if p is not None:
                    if p.color == attacker_color and p.kind in (ROOK, QUEEN):
                        return True
                    break
                f += df
                r += dr

        for df, dr in directions_diag:
            f, r = target_file + df, target_rank + dr
            while is_on_board(f, r):
                p = self.board.get(coords_to_square(f, r))
                if p is not None:
                    if p.color == attacker_color and p.kind in (BISHOP, QUEEN):
                        return True
                    break
                f += df
                r += dr

        return False

    def _move_leaves_king_in_check(self, origin: str, destination: str) -> bool:
        """Try the move on a board copy and report whether own king ends up attacked."""
        piece = self.board[origin]
        ep_capture_square: Optional[str] = None
        if (
            piece.kind == PAWN
            and self.en_passant_target == destination
            and destination not in self.board
            and origin[0] != destination[0]
        ):
            ep_capture_square = destination[0] + origin[1]

        castling_side: Optional[str] = None
        if piece.kind == KING and abs(square_to_coords(destination)[0] - square_to_coords(origin)[0]) == 2:
            castling_side = "K" if FILES.index(destination[0]) == 6 else "Q"

        saved_board = self.board
        self.board = dict(saved_board)
        try:
            if ep_capture_square is not None and ep_capture_square in self.board:
                del self.board[ep_capture_square]
            self.board[destination] = piece
            if origin in self.board:
                del self.board[origin]
            if castling_side is not None:
                rank = origin[1]
                if castling_side == "K":
                    self.board[("f" + rank)] = self.board.pop("h" + rank)
                else:
                    self.board[("d" + rank)] = self.board.pop("a" + rank)
            return self.is_in_check(piece.color)
        finally:
            self.board = saved_board

    def _count_legal_moves(self, color: str) -> int:
        count = 0
        for square, piece in list(self.board.items()):
            if piece.color != color:
                continue
            for target in self._candidate_moves(square, piece):
                if not self._move_leaves_king_in_check(square, target):
                    count += 1
        return count

    # ------------------------------------------------------------------
    # Draw conditions
    # ------------------------------------------------------------------

    def _is_insufficient_material(self) -> bool:
        """Detect drawn endgames where neither side can force a mate.

        Covers the standard FIDE cases:
          - K vs K
          - K + bishop vs K
          - K + knight vs K
          - K + bishop(s) vs K + bishop(s), all bishops on same colour squares
        """
        per_color: dict[str, list[Piece]] = {WHITE: [], BLACK: []}
        for piece in self.board.values():
            if piece.kind == KING:
                continue
            per_color[piece.color].append(piece)

        # Any pawn, rook, or queen on the board => mating material exists.
        for pieces in per_color.values():
            for p in pieces:
                if p.kind in (PAWN, ROOK, QUEEN):
                    return False

        w = per_color[WHITE]
        b = per_color[BLACK]

        # K vs K
        if not w and not b:
            return True
        # K + minor (bishop or knight) vs K
        if len(w) == 1 and not b and w[0].kind in (BISHOP, KNIGHT):
            return True
        if len(b) == 1 and not w and b[0].kind in (BISHOP, KNIGHT):
            return True
        # Two knights vs lone king isn't a forced mate, but it's mate-possible
        # against a cooperative opponent so we conservatively don't claim draw.
        # Bishops vs bishops all on same colour squares
        if all(p.kind == BISHOP for p in (w + b)) and (w or b):
            squares = [sq for sq, p in self.board.items() if p.kind == BISHOP]
            colours = {(FILES.index(s[0]) + RANKS.index(s[1])) % 2 for s in squares}
            if len(colours) == 1:
                return True

        return False

    def _position_signature(self) -> str:
        """Compact, FEN-like signature of the position.

        Includes everything that determines whether two positions are
        "the same" for the purpose of threefold repetition: piece placement,
        side to move, castling rights, and en-passant target.
        """
        pieces = ";".join(
            f"{sq}:{p.color[0]}{p.kind[0]}"
            for sq, p in sorted(self.board.items(), key=lambda item: square_sort_key(item[0]))
        )
        castling = (
            ("K" if self.castling_rights[WHITE]["K"] else "")
            + ("Q" if self.castling_rights[WHITE]["Q"] else "")
            + ("k" if self.castling_rights[BLACK]["K"] else "")
            + ("q" if self.castling_rights[BLACK]["Q"] else "")
        ) or "-"
        ep = self.en_passant_target or "-"
        return f"{pieces}|{self.turn}|{castling}|{ep}"

    def _bump_position_count(self) -> None:
        sig = self._position_signature()
        self.position_counts[sig] = self.position_counts.get(sig, 0) + 1

    def _is_threefold_repetition(self) -> bool:
        return any(count >= 3 for count in self.position_counts.values())

    def _current_status(self) -> tuple[str, Optional[str], bool]:
        """Return ``(status, winner, in_check)`` for the side to move.

        Uses the cached value computed at the end of ``move()`` when present,
        and otherwise computes from scratch (e.g. for the initial state or
        right after ``undo``).
        """
        if self._cached_status is not None:
            return self._cached_status

        in_check = self.is_in_check(self.turn)
        legal_count = self._count_legal_moves(self.turn)

        if legal_count == 0 and in_check:
            status = "checkmate"
            winner = opponent(self.turn)
        elif legal_count == 0:
            status = "stalemate"
            winner = None
        elif self._is_insufficient_material():
            status = "draw_insufficient"
            winner = None
        elif self.halfmove_clock >= 100:
            status = "draw_fifty_move"
            winner = None
        elif self._is_threefold_repetition():
            status = "draw_repetition"
            winner = None
        else:
            status = "active"
            winner = None

        self._cached_status = (status, winner, in_check)
        return self._cached_status

    # ------------------------------------------------------------------
    # SAN building
    # ------------------------------------------------------------------

    def _build_san(
        self,
        *,
        piece: Piece,
        source: str,
        destination: str,
        captured: bool,
        castling: Optional[str],
        promotion_kind: Optional[str],
        is_check: bool,
        is_checkmate: bool,
    ) -> str:
        if castling == "K":
            base = "O-O"
        elif castling == "Q":
            base = "O-O-O"
        elif piece.kind == PAWN:
            base = f"{source[0]}x{destination}" if captured else destination
            if promotion_kind:
                base += "=" + SAN_LETTERS.get(promotion_kind, promotion_kind[0].upper())
        else:
            letter = SAN_LETTERS[piece.kind]
            disambiguation = self._san_disambiguation(piece, source, destination)
            base = f"{letter}{disambiguation}{'x' if captured else ''}{destination}"

        if is_checkmate:
            return base + "#"
        if is_check:
            return base + "+"
        return base

    def _san_disambiguation(self, piece: Piece, source: str, destination: str) -> str:
        """Compute the smallest SAN disambiguation prefix for the piece that just moved.

        Called AFTER the move is applied. We temporarily roll the moving piece back to
        its source so we can ask: which other same-kind same-color pieces could also
        have legally reached `destination` from the prior position?
        """
        same_kind_squares: list[str] = []
        original_dest = self.board.get(destination)
        self.board[source] = piece
        if destination in self.board:
            del self.board[destination]
        try:
            for sq, p in list(self.board.items()):
                if sq == source:
                    continue
                if p.color != piece.color or p.kind != piece.kind:
                    continue
                if destination in self._candidate_moves(sq, p):
                    if not self._move_leaves_king_in_check(sq, destination):
                        same_kind_squares.append(sq)
        finally:
            if original_dest is not None:
                self.board[destination] = original_dest
            elif destination in self.board:
                del self.board[destination]
            if source in self.board:
                del self.board[source]

        if not same_kind_squares:
            return ""

        same_file = [s for s in same_kind_squares if s[0] == source[0]]
        same_rank = [s for s in same_kind_squares if s[1] == source[1]]

        if not same_file:
            return source[0]
        if not same_rank:
            return source[1]
        return source

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_promotion_rank(self, color: str, square: str) -> bool:
        _, rank_index = square_to_coords(square)
        return (color == WHITE and rank_index == 7) or (color == BLACK and rank_index == 0)

    def _initial_board(self) -> dict[str, Piece]:
        board: dict[str, Piece] = {}
        back_rank = [ROOK, KNIGHT, BISHOP, QUEEN, KING, BISHOP, KNIGHT, ROOK]

        for file_index, kind in enumerate(back_rank):
            file_name = FILES[file_index]
            board[f"{file_name}1"] = Piece(WHITE, kind)
            board[f"{file_name}2"] = Piece(WHITE, PAWN)
            board[f"{file_name}7"] = Piece(BLACK, PAWN)
            board[f"{file_name}8"] = Piece(BLACK, kind)

        return board

    def _color_label(self, color: str) -> str:
        if color == WHITE:
            return "Albe"
        if color == BLACK:
            return "Negre"
        raise InvalidMoveError(f"Culoare necunoscuta: {color}.")


def square_sort_key(square: str) -> tuple[int, int]:
    file_index, rank_index = square_to_coords(square)
    return rank_index, file_index
