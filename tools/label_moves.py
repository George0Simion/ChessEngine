"""Annotate moves in parsed games with Best / Excellent / Good / Inaccuracy /
Mistake / Blunder, based on the engine's cp loss vs the position-best move.

Output JSONL: one record per labeled game, with parallel arrays.

    {
      "id": ..., "result": "...",
      "moves_uci": [...],
      "labels":  ["Best", "Good", "Inaccuracy", ...],   # per ply
      "cp_loss": [3, 84, 240, ...]                       # capped, in centipawns
    }

Usage:
    python -m tools.label_moves --in data/games.jsonl --out data/labeled.jsonl
        [--time-ms 80] [--max-games N] [--cp-cap 1000]
"""

from __future__ import annotations
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.board import Position
from engine.types import FEN_START, square_from_name, KNIGHT, BISHOP, ROOK, QUEEN, MATE, MATE_IN_MAX
from engine.movegen import generate_moves
from engine.search import Searcher
from engine.tt import TranspositionTable


def label_for_loss(cp_loss: int) -> str:
    if cp_loss <= 20:   return "Best"
    if cp_loss <= 50:   return "Excellent"
    if cp_loss <= 100:  return "Good"
    if cp_loss <= 250:  return "Inaccuracy"
    if cp_loss <= 500:  return "Mistake"
    return "Blunder"


def uci_to_move(pos, uci):
    from engine.types import move_from, move_to, move_promo
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
    return None


def normalize_cp(score: int, cap: int) -> int:
    """Clamp mate scores into the cap range so we don't label cosmetic moves
    in won positions as Blunders."""
    if score > MATE_IN_MAX:
        return cap
    if score < -MATE_IN_MAX:
        return -cap
    if score > cap:  return cap
    if score < -cap: return -cap
    return score


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--time-ms", type=int, default=80, help="per-position search budget")
    ap.add_argument("--max-games", type=int, default=0)
    ap.add_argument("--cp-cap", type=int, default=1000, help="cap |cp| before labeling")
    args = ap.parse_args()

    tt = TranspositionTable(mb=32)
    searcher = Searcher(tt)

    os.makedirs(os.path.dirname(args.dst) or ".", exist_ok=True)
    n_done = 0
    with open(args.src, "r", encoding="utf-8") as f, \
         open(args.dst, "w", encoding="utf-8") as out:
        for line in f:
            line = line.strip()
            if not line: continue
            if args.max_games and n_done >= args.max_games:
                break
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            moves = rec.get("moves_uci") or []
            if not moves:
                continue

            labels = []
            losses = []
            pos = Position.from_fen(FEN_START)
            tt.clear()
            for uci in moves:
                played = uci_to_move(pos, uci)
                if played is None:
                    break
                # Best move score (positive = good for STM)
                r = searcher.search(pos, time_ms=args.time_ms)
                best_score = normalize_cp(r.score, args.cp_cap)

                # Score after the played move (from OPPONENT POV after our move).
                pos.make_move(played)
                r2 = searcher.search(pos, time_ms=args.time_ms)
                played_score_from_stm = -normalize_cp(r2.score, args.cp_cap)
                # cp_loss is how much worse than the best the played move is.
                cp_loss = max(0, best_score - played_score_from_stm)
                labels.append(label_for_loss(cp_loss))
                losses.append(cp_loss)

            out.write(json.dumps({
                "id": rec.get("id"),
                "result": rec.get("result"),
                "moves_uci": moves[: len(labels)],
                "labels": labels,
                "cp_loss": losses,
            }, separators=(",", ":")) + "\n")
            n_done += 1
            if n_done % 50 == 0:
                print(f"  labeled {n_done} games", file=sys.stderr)

    print(f"labeled {n_done} games -> {args.dst}", file=sys.stderr)


if __name__ == "__main__":
    main()
