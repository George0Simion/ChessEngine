"""Build an opening book from a JSONL of games (output of parse_kaggle_games.py).

We aggregate move frequencies per position (keyed by *our* engine's Zobrist
hash, hex-encoded) up to a configurable ply limit. Optionally filter by
rating so the book leans toward stronger play.

Output JSON shape (loaded by engine/book.py):

    {
      "<zobrist_hex>": [
        ["e2e4", 1234, 1750],
        ["d2d4",  812, 1730],
        ...
      ],
      ...
    }

Usage:
    python -m tools.build_opening_book --in data/games.jsonl --out data/opening_book.json
        [--max-ply 16] [--min-rating 1700] [--min-freq 3] [--top-k 6]
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from collections import defaultdict

# We use OUR engine to hash positions so engine/book.py can find them.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.board import Position
from engine.types import FEN_START, square_from_name, KNIGHT, BISHOP, ROOK, QUEEN
from engine.movegen import generate_moves


def _uci_to_engine_move(pos: Position, uci: str):
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--max-ply", type=int, default=16)
    ap.add_argument("--min-rating", type=int, default=1700,
                    help="games below this avg rating are skipped")
    ap.add_argument("--min-freq", type=int, default=3,
                    help="drop moves played fewer than N times")
    ap.add_argument("--top-k", type=int, default=6,
                    help="keep at most K moves per position")
    args = ap.parse_args()

    # counts[hash][uci] -> (count, rating_sum, rating_n)
    counts = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))

    n_games = 0
    with open(args.src, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            avg = rec.get("avg_rating")
            if avg is None or avg < args.min_rating:
                continue
            moves = rec.get("moves_uci") or []
            if not moves:
                continue

            pos = Position.from_fen(FEN_START)
            for ply, uci in enumerate(moves[: args.max_ply]):
                key = format(pos.zobrist, "x")
                slot = counts[key][uci]
                slot[0] += 1
                slot[1] += avg
                slot[2] += 1

                m = _uci_to_engine_move(pos, uci)
                if m is None:
                    break
                pos.make_move(m)

            n_games += 1
            if n_games % 10000 == 0:
                print(f"  processed {n_games} games, positions={len(counts)}", file=sys.stderr)

    # Filter + cap
    book = {}
    for key, by_move in counts.items():
        rows = []
        for uci, (c, rs, rn) in by_move.items():
            if c < args.min_freq:
                continue
            avg = rs // rn if rn else 0
            rows.append([uci, c, avg])
        if not rows:
            continue
        rows.sort(key=lambda r: -r[1])
        if args.top_k > 0:
            rows = rows[: args.top_k]
        book[key] = rows

    os.makedirs(os.path.dirname(args.dst) or ".", exist_ok=True)
    with open(args.dst, "w", encoding="utf-8") as out:
        json.dump(book, out, separators=(",", ":"))
    print(f"wrote {len(book)} positions to {args.dst}", file=sys.stderr)


if __name__ == "__main__":
    main()
