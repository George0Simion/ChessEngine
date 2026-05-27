"""Minimal UCI-like CLI.

Supports (case-insensitive):

    uci
    isready
    ucinewgame
    position startpos [moves <uci> ...]
    position fen <FEN> [moves <uci> ...]
    go [movetime <ms>] [depth <n>] [wtime <ms>] [btime <ms>] [winc <ms>] [binc <ms>]
    stop
    quit
    d       (debug: print board / FEN)
    eval    (static evaluation from STM POV)

Emits `info ...` lines after each completed ID iteration plus a final
`bestmove` line.
"""

from __future__ import annotations
import sys
from typing import List, Optional

from .board import Position
from .search import Searcher, SearchResult
from .tt import TranspositionTable
from .types import (
    FEN_START, move_from, move_to, move_promo, move_to_uci,
    KNIGHT, BISHOP, ROOK, QUEEN, MATE, MATE_IN_MAX,
    square_from_name, WHITE,
)
from .movegen import generate_moves
from . import book as opening_book


def _uci_to_move(pos: Position, uci: str) -> int:
    """Translate a UCI string into our packed move format (must be legal)."""
    uci = uci.strip().lower()
    if len(uci) < 4:
        raise ValueError(f"bad uci: {uci!r}")
    frm = square_from_name(uci[0:2])
    to  = square_from_name(uci[2:4])
    promo_ch = uci[4] if len(uci) >= 5 else None
    promo_pt = {"n": KNIGHT, "b": BISHOP, "r": ROOK, "q": QUEEN}.get(promo_ch, 0)
    for m in generate_moves(pos):
        if move_from(m) == frm and move_to(m) == to:
            if promo_pt and move_promo(m) != promo_pt:
                continue
            if (not promo_pt) and move_promo(m):
                continue
            return m
    raise ValueError(f"illegal uci move: {uci!r}")


class UCI:
    def __init__(self):
        self.pos = Position.from_fen(FEN_START)
        self.tt = TranspositionTable(mb=32)
        self.searcher = Searcher(self.tt)

    # ------------------------------------------------------------ I/O
    def loop(self) -> None:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            self._dispatch(line)

    def _send(self, s: str) -> None:
        print(s, flush=True)

    # ------------------------------------------------------------ dispatch
    def _dispatch(self, line: str) -> None:
        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]
        if cmd == "uci":
            self._send("id name ChessMate-Engine 0.2")
            self._send("id author ChessMate Team")
            self._send("uciok")
        elif cmd == "isready":
            self._send("readyok")
        elif cmd == "ucinewgame":
            self.tt.clear()
            self.pos = Position.from_fen(FEN_START)
        elif cmd == "position":
            self._cmd_position(args)
        elif cmd == "go":
            self._cmd_go(args)
        elif cmd == "stop":
            if self.searcher.tm is not None:
                self.searcher.tm.stop()
        elif cmd == "quit":
            sys.exit(0)
        elif cmd == "d":
            self._send(str(self.pos))
            self._send("fen: " + self.pos.to_fen())
        elif cmd == "eval":
            from .evaluate import evaluate
            self._send(f"eval (stm) = {evaluate(self.pos)}")
        # Unknown commands: be lenient.

    # ------------------------------------------------------------ position
    def _cmd_position(self, args: List[str]) -> None:
        if not args:
            return
        idx = 0
        if args[0] == "startpos":
            self.pos = Position.from_fen(FEN_START)
            idx = 1
        elif args[0] == "fen":
            fen_parts = args[1:7]
            self.pos = Position.from_fen(" ".join(fen_parts))
            idx = 7
        if idx < len(args) and args[idx] == "moves":
            for uci in args[idx + 1:]:
                m = _uci_to_move(self.pos, uci)
                self.pos.make_move(m)

    # ------------------------------------------------------------ go
    def _cmd_go(self, args: List[str]) -> None:
        movetime: Optional[int] = None
        depth: Optional[int] = None
        wtime = btime = winc = binc = None
        i = 0
        while i < len(args):
            a = args[i]
            if a == "movetime" and i + 1 < len(args):
                movetime = int(args[i + 1]); i += 2
            elif a == "depth" and i + 1 < len(args):
                depth = int(args[i + 1]); i += 2
            elif a == "wtime" and i + 1 < len(args):
                wtime = int(args[i + 1]); i += 2
            elif a == "btime" and i + 1 < len(args):
                btime = int(args[i + 1]); i += 2
            elif a == "winc" and i + 1 < len(args):
                winc = int(args[i + 1]); i += 2
            elif a == "binc" and i + 1 < len(args):
                binc = int(args[i + 1]); i += 2
            else:
                i += 1

        if movetime is None:
            stm_time = wtime if self.pos.side == WHITE else btime
            stm_inc  = winc  if self.pos.side == WHITE else binc
            if stm_time is not None:
                movetime = max(50, stm_time // 30 + (stm_inc or 0) // 2)
            else:
                movetime = 1000

        # Book first.
        bm = opening_book.probe(self.pos)
        if bm:
            uci = move_to_uci(bm)
            self._send(f"info depth 0 score cp 0 nodes 0 pv {uci} string source book")
            self._send(f"bestmove {uci}")
            return

        def _info(res: SearchResult) -> None:
            if abs(res.score) > MATE_IN_MAX:
                plies = MATE - abs(res.score)
                mate_n = ((plies + 1) // 2) * (1 if res.score > 0 else -1)
                score_str = f"mate {mate_n}"
            else:
                score_str = f"cp {res.score}"
            pv_str = " ".join(move_to_uci(m) for m in res.pv)
            nps = int(res.nodes * 1000 / max(1, res.ms))
            self._send(
                f"info depth {res.depth} score {score_str} "
                f"nodes {res.nodes} nps {nps} time {res.ms} pv {pv_str}"
            )

        result = self.searcher.search(self.pos, time_ms=movetime,
                                       max_depth=depth, info_callback=_info)
        if not result.best_move:
            self._send("bestmove 0000")
            return
        self._send(f"bestmove {move_to_uci(result.best_move)}")


def main() -> None:
    UCI().loop()


if __name__ == "__main__":
    main()
