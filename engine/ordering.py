"""Move ordering: TT move first, then good captures (MVV-LVA), promotions,
killers, counter-moves, and the history heuristic.
"""

from __future__ import annotations
from typing import List, Optional

from .types import (
    PAWN, QUEEN,
    PIECE_VALUE,
    F_CAPTURE, F_PROMO, F_PROMO_CAPTURE, F_EP_CAPTURE,
    piece_type, move_from, move_to, move_flag, move_promo, NO_MOVE,
)
from .board import Position


def _mvv_lva(victim_pt: int, attacker_pt: int) -> int:
    """Most-valuable-victim / least-valuable-attacker score."""
    return PIECE_VALUE[victim_pt] * 10 - PIECE_VALUE[attacker_pt]


class History:
    """Per-search killer / history / counter-move tables.

    - killers[ply]    : up to 2 quiet moves per ply that caused a beta cutoff
    - history[f][t]   : success counter for quiet moves (depth² reward)
    - counter[f][t]   : best response to the previously-played move
    """

    __slots__ = ("killers", "history", "counter", "last_move")

    def __init__(self, max_ply: int = 128):
        self.killers: List[List[int]] = [[NO_MOVE, NO_MOVE] for _ in range(max_ply)]
        self.history: List[List[int]] = [[0] * 64 for _ in range(64)]
        self.counter: List[List[int]] = [[NO_MOVE] * 64 for _ in range(64)]
        self.last_move: int = NO_MOVE

    def store_killer(self, ply: int, move: int) -> None:
        if ply >= len(self.killers):
            return
        slot = self.killers[ply]
        if slot[0] != move:
            slot[1] = slot[0]
            slot[0] = move

    def is_killer(self, ply: int, move: int) -> bool:
        if ply >= len(self.killers):
            return False
        slot = self.killers[ply]
        return move == slot[0] or move == slot[1]

    def add_history(self, move: int, depth: int) -> None:
        f = move_from(move); t = move_to(move)
        bonus = depth * depth
        # Cap to keep numbers comparable across the search.
        v = self.history[f][t] + bonus
        if v > 32_000:
            # Gentle aging — halve all entries.
            for fr in range(64):
                row = self.history[fr]
                for to in range(64):
                    row[to] >>= 1
            v >>= 1
        self.history[f][t] = v

    def get_history(self, move: int) -> int:
        return self.history[move_from(move)][move_to(move)]

    def store_counter(self, prev_move: int, reply: int) -> None:
        if prev_move == NO_MOVE:
            return
        self.counter[move_from(prev_move)][move_to(prev_move)] = reply

    def get_counter(self) -> int:
        if self.last_move == NO_MOVE:
            return NO_MOVE
        return self.counter[move_from(self.last_move)][move_to(self.last_move)]


def score_move(pos: Position, m: int, tt_move: int, history: History, ply: int) -> int:
    """Higher score => earlier in the search."""
    if m == tt_move:
        return 10_000_000

    flag = move_flag(m)

    if flag == F_CAPTURE or flag == F_PROMO_CAPTURE:
        victim   = pos.board[move_to(m)]
        attacker = pos.board[move_from(m)]
        v_pt = piece_type(victim)   if victim   else PAWN
        a_pt = piece_type(attacker) if attacker else PAWN
        s = 2_000_000 + _mvv_lva(v_pt, a_pt)
        if flag == F_PROMO_CAPTURE:
            s += PIECE_VALUE[QUEEN] + move_promo(m) * 100
        return s

    if flag == F_EP_CAPTURE:
        return 2_000_000 + _mvv_lva(PAWN, PAWN)

    if flag == F_PROMO:
        # Queen promotion ranks highest.
        return 1_500_000 + PIECE_VALUE.get(move_promo(m), 0)

    if history.is_killer(ply, m):
        return 900_000

    counter = history.get_counter()
    if counter == m:
        return 800_000

    return history.get_history(m)


def order_moves(pos: Position, moves: List[int], tt_move: int,
                history: Optional[History], ply: int) -> List[int]:
    if history is None:
        history = History()
    # Score once and sort. Avoid per-comparator score calls.
    keyed = [(score_move(pos, m, tt_move, history, ply), m) for m in moves]
    keyed.sort(reverse=True)
    return [m for _, m in keyed]
