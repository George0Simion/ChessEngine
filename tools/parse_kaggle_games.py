"""Parse the Kaggle Lichess CSV into a streamlined JSONL of per-game records.

Output schema (one JSON object per line):
    {
      "id": <int>,
      "result": "1-0" | "0-1" | "1/2-1/2",
      "avg_rating": <int|null>,
      "rating_diff": <int|null>,
      "mode": <str>,
      "termination": <str>,
      "moves_uci": ["e2e4", "g8f6", ...],
      "fens": ["<FEN after ply 1>", "<FEN after ply 2>", ...]  # length == len(moves)
    }

Usage:
    python -m tools.parse_kaggle_games --in lichess-08-2014.csv --out data/games.jsonl
        [--limit N] [--min-rating R]
"""

from __future__ import annotations
import argparse
import csv
import json
import os
import re
import sys
from typing import Iterable

try:
    import chess
    import chess.pgn
except ImportError:
    print("This tool requires python-chess. Install with: pip install python-chess", file=sys.stderr)
    sys.exit(1)


_RESULT_MAP = {
    "white wins": "1-0",
    "black wins": "0-1",
    "draw": "1/2-1/2",
    "drawn": "1/2-1/2",
}

# Strip move-number tokens and result tokens from a SAN move list string.
_MOVENUM_RE = re.compile(r"\d+\.(\.\.)?\s*")
_RESULT_TOKEN_RE = re.compile(r"\s*(1-0|0-1|1/2-1/2|\*)\s*$")


def san_tokens(movetext: str):
    s = _MOVENUM_RE.sub("", movetext)
    s = _RESULT_TOKEN_RE.sub("", s)
    return s.split()


def replay_to_uci(movetext: str):
    """Yield (uci_move, fen_after) for each ply, using python-chess for SAN parsing."""
    board = chess.Board()
    for san in san_tokens(movetext):
        if not san or san in ("0-1", "1-0", "1/2-1/2", "*"):
            continue
        try:
            mv = board.parse_san(san)
        except (ValueError, chess.IllegalMoveError, chess.AmbiguousMoveError):
            # Malformed game — drop the rest.
            break
        uci = mv.uci()
        board.push(mv)
        yield uci, board.fen()


def iter_csv_rows(path: str) -> Iterable[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


def to_int(s):
    if s is None or s == "":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True, help="path to Kaggle CSV")
    ap.add_argument("--out", dest="dst", required=True, help="output JSONL path")
    ap.add_argument("--limit", type=int, default=0, help="max games to process (0 = all)")
    ap.add_argument("--min-rating", type=int, default=0, help="skip games below avg rating")
    ap.add_argument("--no-fens", action="store_true", help="omit per-ply FENs (smaller output)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.dst) or ".", exist_ok=True)

    n_in = 0
    n_out = 0
    with open(args.dst, "w", encoding="utf-8") as out:
        for row in iter_csv_rows(args.src):
            n_in += 1
            if args.limit and n_out >= args.limit:
                break
            avg = to_int(row.get("Average Rating") or row.get("AverageRating"))
            if args.min_rating and (avg is None or avg < args.min_rating):
                continue

            result_raw = (row.get("Result") or "").strip().lower()
            result = _RESULT_MAP.get(result_raw, result_raw or "*")
            pgn = row.get("PGN") or row.get("AN") or row.get("moves") or ""

            moves_uci = []
            fens = []
            for uci, fen in replay_to_uci(pgn):
                moves_uci.append(uci)
                if not args.no_fens:
                    fens.append(fen)
            if not moves_uci:
                continue

            rec = {
                "id": n_in,
                "result": result,
                "avg_rating": avg,
                "rating_diff": to_int(row.get("Rating Difference")),
                "mode": (row.get("Mode") or "").strip() or None,
                "termination": (row.get("Termination Type") or "").strip() or None,
                "moves_uci": moves_uci,
            }
            if not args.no_fens:
                rec["fens"] = fens
            out.write(json.dumps(rec, separators=(",", ":")) + "\n")
            n_out += 1

            if n_in % 5000 == 0:
                print(f"  parsed {n_in} read, {n_out} written", file=sys.stderr)

    print(f"done. read={n_in} written={n_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
