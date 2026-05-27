"""Search: iterative deepening with aspiration windows, principal variation
search, late move reductions, transposition table, killer + history + counter
move ordering, quiescence search (with in-check evasions and delta pruning),
null-move pruning, and check extensions.

The public entry point is `Searcher.search(pos, time_ms, max_depth)`.
"""

from __future__ import annotations
from typing import List, Optional, Tuple, Callable

from .types import (
    INF, MATE, MATE_IN_MAX, NO_MOVE,
    PAWN, KING, PIECE_VALUE,
    move_to, move_flag, move_promo,
    F_CAPTURE, F_EP_CAPTURE, F_PROMO, F_PROMO_CAPTURE,
    piece_type, piece_color,
)
from .board import Position
from .movegen import generate_moves, generate_captures
from .evaluate import evaluate
from .ordering import order_moves, History
from .tt import TranspositionTable, TT_EXACT, TT_LOWER, TT_UPPER
from .time_manager import TimeManager


# Time is polled every N nodes (must be a power of 2 for the bitmask).
_TIME_CHECK_MASK = 4095


class SearchResult:
    __slots__ = ("best_move", "score", "depth", "nodes", "pv", "ms",
                 "completed_depth")

    def __init__(self, best_move=NO_MOVE, score=0, depth=0, nodes=0,
                 pv=None, ms=0, completed_depth=0):
        self.best_move = best_move
        self.score = score
        self.depth = depth
        self.nodes = nodes
        self.pv = pv or []
        self.ms = ms
        self.completed_depth = completed_depth


class _AbortSearch(Exception):
    pass


class Searcher:
    def __init__(self, tt: Optional[TranspositionTable] = None):
        self.tt = tt or TranspositionTable(mb=32)
        self.history = History()
        self.nodes = 0
        self.tm: Optional[TimeManager] = None
        self.pos: Optional[Position] = None
        self.aborted = False
        self.root_best_move = NO_MOVE
        self.root_best_score = 0
        self.qsearch_max_ply = 32   # safety cap for in-check evasion explosion

    # ------------------------------------------------------------------
    def search(self, pos: Position, time_ms: int,
               max_depth: Optional[int] = None,
               info_callback: Optional[Callable[[SearchResult], None]] = None
               ) -> SearchResult:
        self.pos = pos
        self.tm = TimeManager(time_ms, max_depth)
        self.history = History()
        self.nodes = 0
        self.aborted = False
        self.root_best_move = NO_MOVE
        self.root_best_score = 0
        self.tt.new_search()

        root_moves = generate_moves(pos)
        if not root_moves:
            return SearchResult(NO_MOVE, 0, 0, 0, [], 0, 0)

        # ALWAYS have a legal fallback. If we run out of time before
        # iteration 1 finishes, this is what we return.
        last_complete = SearchResult(
            best_move=root_moves[0], score=0, depth=0, nodes=0,
            pv=[root_moves[0]], ms=0, completed_depth=0,
        )

        if len(root_moves) == 1:
            last_complete.ms = self.tm.elapsed_ms()
            return last_complete

        prev_score = 0
        depth = 1
        while True:
            if not self.tm.should_start_iteration(depth):
                break
            try:
                if depth >= 4 and abs(prev_score) < MATE_IN_MAX:
                    score, best, pv = self._aspiration_root(depth, root_moves,
                                                             prev_score)
                else:
                    score, best, pv = self._root_search(depth, root_moves,
                                                         -INF, INF)
            except _AbortSearch:
                self.aborted = True
                # Salvage: if we have any root_best_move from this iteration,
                # promote it (it was found at a deeper depth than the last
                # completed iteration, so it's likely better).
                if self.root_best_move != NO_MOVE:
                    last_complete = SearchResult(
                        best_move=self.root_best_move,
                        score=self.root_best_score,
                        depth=depth,
                        nodes=self.nodes,
                        pv=[self.root_best_move],
                        ms=self.tm.elapsed_ms(),
                        completed_depth=last_complete.completed_depth,
                    )
                break

            last_complete = SearchResult(
                best_move=best, score=score, depth=depth,
                nodes=self.nodes, pv=pv, ms=self.tm.elapsed_ms(),
                completed_depth=depth,
            )
            prev_score = score

            if info_callback is not None:
                info_callback(last_complete)

            # Found a mate — no point searching further.
            if abs(score) > MATE_IN_MAX:
                break
            depth += 1

        last_complete.ms = self.tm.elapsed_ms()
        return last_complete

    # ------------------------------------------------------------------
    def _aspiration_root(self, depth: int, root_moves: List[int],
                          prev_score: int) -> Tuple[int, int, List[int]]:
        """Run the root search with an aspiration window around prev_score."""
        delta = 30
        alpha = prev_score - delta
        beta  = prev_score + delta
        while True:
            score, best, pv = self._root_search(depth, root_moves, alpha, beta)
            if self.aborted:
                raise _AbortSearch()
            if score <= alpha:
                beta = (alpha + beta) // 2
                alpha = max(-INF, score - delta)
                delta *= 2
            elif score >= beta:
                beta = min(INF, score + delta)
                delta *= 2
            else:
                return score, best, pv
            if delta > 800:
                return self._root_search(depth, root_moves, -INF, INF)

    # ------------------------------------------------------------------
    def _root_search(self, depth: int, root_moves: List[int],
                      alpha: int, beta: int) -> Tuple[int, int, List[int]]:
        pos = self.pos
        a = alpha
        best_score = -INF
        best_move = root_moves[0]
        pv: List[int] = [best_move]

        tt_entry = self.tt.probe(pos.zobrist)
        tt_move = tt_entry[4] if tt_entry else NO_MOVE
        ordered = order_moves(pos, root_moves, tt_move, self.history, 0)

        for i, m in enumerate(ordered):
            pos.make_move(m)
            self.nodes += 1
            child_pv: List[int] = []
            prev_last = self.history.last_move
            self.history.last_move = m

            if i == 0:
                score = -self._negamax(depth - 1, -beta, -a, 1, child_pv, True)
            else:
                score = -self._negamax(depth - 1, -a - 1, -a, 1, child_pv, True)
                if a < score < beta:
                    child_pv = []
                    score = -self._negamax(depth - 1, -beta, -a, 1, child_pv, True)

            self.history.last_move = prev_last
            pos.unmake_move(m)
            if self.aborted:
                raise _AbortSearch()

            if score > best_score:
                best_score = score
                best_move = m
                pv = [m] + child_pv
                self.root_best_move = m
                self.root_best_score = score
                if score > a:
                    a = score

        # Mark TT with EXACT only if we have a meaningful root score
        # (full-window fail-low at root is rare but possible inside aspiration).
        flag = TT_EXACT
        if best_score <= alpha:
            flag = TT_UPPER
        elif best_score >= beta:
            flag = TT_LOWER
        self.tt.store(pos.zobrist, depth, flag, best_score, best_move)

        return best_score, best_move, pv

    # ------------------------------------------------------------------
    def _check_time(self) -> None:
        if (self.nodes & _TIME_CHECK_MASK) == 0 and self.tm.should_stop():
            self.aborted = True
            raise _AbortSearch()

    # ------------------------------------------------------------------
    def _negamax(self, depth: int, alpha: int, beta: int, ply: int,
                  pv_out: List[int], allow_null: bool) -> int:
        self._check_time()
        pos = self.pos

        # Draws — never at the root.
        if ply > 0 and pos.is_drawn():
            return 0

        in_check = pos.in_check()
        # Check extension.
        if in_check:
            depth += 1

        if depth <= 0:
            return self._qsearch(alpha, beta, ply, 0)

        alpha_orig = alpha

        # ---- TT probe (with bound tightening) ----
        tt_move = NO_MOVE
        tt_entry = self.tt.probe(pos.zobrist)
        if tt_entry is not None:
            tt_move = tt_entry[4]
            tt_depth = tt_entry[1]
            tt_score = tt_entry[3]
            tt_flag = tt_entry[2]
            if tt_depth >= depth and ply > 0:
                if tt_flag == TT_EXACT:
                    return tt_score
                if tt_flag == TT_LOWER:
                    if tt_score >= beta:
                        return tt_score
                    if tt_score > alpha:
                        alpha = tt_score
                elif tt_flag == TT_UPPER:
                    if tt_score <= alpha:
                        return tt_score
                    if tt_score < beta:
                        beta = tt_score
                if alpha >= beta:
                    return tt_score

        # ---- Null-move pruning ----
        if (allow_null and not in_check and depth >= 3
                and self._has_non_pawn_material()):
            R = 2 if depth < 6 else 3
            pos.make_null()
            self.nodes += 1
            prev_last = self.history.last_move
            self.history.last_move = NO_MOVE
            child_pv: List[int] = []
            score = -self._negamax(depth - 1 - R, -beta, -beta + 1, ply + 1,
                                    child_pv, False)
            self.history.last_move = prev_last
            pos.unmake_null()
            if self.aborted:
                raise _AbortSearch()
            if score >= beta and abs(score) < MATE_IN_MAX:
                return score

        # ---- Move generation ----
        moves = generate_moves(pos)
        if not moves:
            return -MATE + ply if in_check else 0

        moves = order_moves(pos, moves, tt_move, self.history, ply)

        best_score = -INF
        best_move = NO_MOVE

        for i, m in enumerate(moves):
            flag = move_flag(m)
            is_tactical = (flag == F_CAPTURE or flag == F_EP_CAPTURE
                            or flag == F_PROMO or flag == F_PROMO_CAPTURE)

            pos.make_move(m)
            self.nodes += 1
            gives_check = pos.in_check()  # opponent now in check
            prev_last = self.history.last_move
            self.history.last_move = m

            child_pv: List[int] = []

            # ---- Late move reductions ----
            do_lmr = (i >= 3 and depth >= 3
                       and not in_check and not gives_check
                       and not is_tactical
                       and not self.history.is_killer(ply, m))
            if do_lmr:
                reduction = 1 + (i >= 6) + (depth >= 6 and i >= 12)
                new_depth = max(0, depth - 1 - reduction)
                score = -self._negamax(new_depth, -alpha - 1, -alpha,
                                         ply + 1, child_pv, True)
                # Re-search at full depth if reduction looked too aggressive.
                if score > alpha:
                    child_pv = []
                    score = -self._negamax(depth - 1, -alpha - 1, -alpha,
                                             ply + 1, child_pv, True)
            elif i == 0:
                score = -self._negamax(depth - 1, -beta, -alpha,
                                         ply + 1, child_pv, True)
            else:
                score = -self._negamax(depth - 1, -alpha - 1, -alpha,
                                         ply + 1, child_pv, True)

            # PVS re-search with full window if we beat alpha on a zero-window.
            if i > 0 and alpha < score < beta:
                child_pv = []
                score = -self._negamax(depth - 1, -beta, -alpha,
                                         ply + 1, child_pv, True)

            self.history.last_move = prev_last
            pos.unmake_move(m)
            if self.aborted:
                raise _AbortSearch()

            if score > best_score:
                best_score = score
                best_move = m
                if score > alpha:
                    alpha = score
                    pv_out.clear()
                    pv_out.append(m)
                    pv_out.extend(child_pv)
                if alpha >= beta:
                    # Beta cutoff — reward quiet moves.
                    if not is_tactical:
                        self.history.store_killer(ply, m)
                        self.history.add_history(m, depth)
                        self.history.store_counter(prev_last, m)
                    break

        # ---- Store TT ----
        if best_score <= alpha_orig:
            tt_flag = TT_UPPER
        elif best_score >= beta:
            tt_flag = TT_LOWER
        else:
            tt_flag = TT_EXACT
        self.tt.store(pos.zobrist, depth, tt_flag, best_score, best_move)

        return best_score

    # ------------------------------------------------------------------
    def _qsearch(self, alpha: int, beta: int, ply: int, qply: int) -> int:
        """Quiescence search.

        - Out-of-check: stand-pat, then search captures and queen-promotions
          with delta pruning.
        - In-check: search ALL legal moves (evasions) so we never stop in a
          tactical noisy spot.
        """
        self._check_time()
        pos = self.pos
        in_check = pos.in_check()

        # Bound qsearch depth to avoid pathological explosions.
        if qply >= self.qsearch_max_ply:
            return evaluate(pos)

        if in_check:
            stand_pat = -INF
            moves = generate_moves(pos)
            if not moves:
                return -MATE + ply
        else:
            stand_pat = evaluate(pos)
            if stand_pat >= beta:
                return stand_pat
            if stand_pat > alpha:
                alpha = stand_pat
            moves = generate_captures(pos)

        if not moves:
            return stand_pat if stand_pat != -INF else 0

        moves = order_moves(pos, moves, NO_MOVE, self.history, ply)

        best_score = stand_pat

        for m in moves:
            flag = move_flag(m)

            # Delta pruning (non-check positions only).
            if not in_check and stand_pat != -INF:
                if flag == F_CAPTURE or flag == F_PROMO_CAPTURE:
                    victim_pc = pos.board[move_to(m)]
                    gain = (PIECE_VALUE[piece_type(victim_pc)]
                             if victim_pc else 0)
                elif flag == F_EP_CAPTURE:
                    gain = PIECE_VALUE[PAWN]
                else:
                    gain = 0
                if flag == F_PROMO or flag == F_PROMO_CAPTURE:
                    gain += PIECE_VALUE[move_promo(m)] - PIECE_VALUE[PAWN]
                if stand_pat + gain + 200 < alpha:
                    continue

            pos.make_move(m)
            self.nodes += 1
            score = -self._qsearch(-beta, -alpha, ply + 1, qply + 1)
            pos.unmake_move(m)
            if self.aborted:
                raise _AbortSearch()

            if score > best_score:
                best_score = score
                if score > alpha:
                    alpha = score
                if alpha >= beta:
                    return score

        return best_score

    # ------------------------------------------------------------------
    def _has_non_pawn_material(self) -> bool:
        side = self.pos.side
        board = self.pos.board
        for s in range(64):
            pc = board[s]
            if pc and piece_color(pc) == side:
                pt = piece_type(pc)
                if pt != PAWN and pt != KING:
                    return True
        return False


def root_move_scores(pos: Position, tt: TranspositionTable,
                     time_ms: int, max_depth: Optional[int] = None
                     ) -> List[Tuple[int, int]]:
    """Convenience: return list of (score, move) pairs for ALL root moves,
    sorted best first. Used by API to pick weighted-random moves at low levels.
    """
    s = Searcher(tt)
    s.pos = pos
    s.tm = TimeManager(time_ms, max_depth)
    s.history = History()
    s.nodes = 0
    s.aborted = False
    tt.new_search()

    moves = generate_moves(pos)
    if not moves:
        return []
    if len(moves) == 1:
        return [(0, moves[0])]

    # Run a quick fixed-depth(ish) search per move at this budget.
    depth = max(1, (max_depth or 4))
    results: List[Tuple[int, int]] = []
    for m in moves:
        pos.make_move(m)
        try:
            pv: List[int] = []
            score = -s._negamax(depth - 1, -INF, INF, 1, pv, True)
        except _AbortSearch:
            pos.unmake_move(m)
            break
        pos.unmake_move(m)
        results.append((score, m))
        if s.tm.should_stop():
            break

    if not results:
        return [(0, moves[0])]
    results.sort(key=lambda kv: -kv[0])
    return results
