"""Extract puzzle candidates from labeled games.

A puzzle is born when one side plays a Mistake/Blunder and the engine sees a
clearly winning followup. We record:
    fen           - position the puzzle starts from (BEFORE the solution)
    solution      - list of UCI moves the engine recommends, capped at K plies
    swing_cp      - cp change between the blunder position and the best line
    theme_guess   - rough tag (e.g. "winning_attack", "material_win")
    difficulty    - rough scaling from swing size + depth
    source        - dict with original game id and ply index

Usage:
    python -m tools.extract_puzzles --labeled data/labeled.jsonl \
        --games data/games.jsonl --out data/puzzles.jsonl
        [--min-swing 250] [--solution-plies 4] [--time-ms 200]
"""

from __future__ import annotations
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.board import Position
from engine.types import FEN_START, square_from_name, KNIGHT, BISHOP, ROOK, QUEEN, MATE_IN_MAX, MATE
from engine.movegen import generate_moves
from engine.search import Searcher
from engine.tt import TranspositionTable


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


def classify(swing: int, mate: bool) -> str:
    if mate:           return "mating_attack"
    if swing >= 700:   return "material_win"
    if swing >= 350:   return "winning_advantage"
    return "tactical"


def difficulty(swing: int, depth: int) -> int:
    """1 (easy) ... 5 (hard)."""
    if depth < 4 and swing > 700:
        return 1
    if depth < 6 and swing > 500:
        return 2
    if depth < 8 and swing > 300:
        return 3
    if depth < 10:
        return 4
    return 5


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labeled", required=True)
    ap.add_argument("--games", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-swing", type=int, default=250)
    ap.add_argument("--solution-plies", type=int, default=4)
    ap.add_argument("--time-ms", type=int, default=200)
    args = ap.parse_args()

    # Index games by id for lookup.
    games = {}
    with open(args.games, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            games[rec.get("id")] = rec

    tt = TranspositionTable(mb=32)
    searcher = Searcher(tt)

    n_in = n_out = 0
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.labeled, "r", encoding="utf-8") as f, \
         open(args.out, "w", encoding="utf-8") as out:
        for line in f:
            n_in += 1
            line = line.strip()
            if not line: continue
            try:
                lab = json.loads(line)
            except json.JSONDecodeError:
                continue
            game = games.get(lab.get("id"))
            if not game:
                continue
            labels = lab.get("labels") or []
            losses = lab.get("cp_loss") or []
            moves = game.get("moves_uci") or []

            # Replay the game and stop at each Mistake/Blunder ply.
            pos = Position.from_fen(FEN_START)
            tt.clear()
            for ply, uci in enumerate(moves):
                if ply >= len(labels):
                    break
                lbl = labels[ply]
                if lbl in ("Mistake", "Blunder") and losses[ply] >= args.min_swing:
                    # The OPPONENT now has a tactical opportunity.
                    # Apply the bad move, then ask the engine for the punishing line.
                    played = uci_to_move(pos, uci)
                    if played is None: break
                    pos.make_move(played)

                    # Build a solution line by repeated best-move search.
                    fen_start = pos.to_fen()
                    solution = []
                    made = []
                    for _ in range(args.solution_plies):
                        r = searcher.search(pos, time_ms=args.time_ms)
                        if not r.best_move:
                            break
                        from engine.types import move_to_uci
                        solution.append(move_to_uci(r.best_move))
                        made.append(r.best_move)
                        pos.make_move(r.best_move)

                    # Score the resulting position from the puzzle solver's POV.
                    final = searcher.search(pos, time_ms=args.time_ms)
                    final_cp = final.score
                    is_mate = abs(final_cp) > MATE_IN_MAX

                    # Roll back the solution moves so we can continue iterating.
                    for mv in reversed(made):
                        pos.unmake_move(mv)

                    swing = losses[ply]
                    if solution and (is_mate or swing >= args.min_swing):
                        out.write(json.dumps({
                            "fen": fen_start,
                            "solution": solution,
                            "swing_cp": swing,
                            "theme_guess": classify(swing, is_mate),
                            "difficulty": difficulty(swing, final.depth),
                            "source": {"game_id": lab.get("id"), "ply": ply,
                                       "result": lab.get("result")},
                        }, separators=(",", ":")) + "\n")
                        n_out += 1
                else:
                    played = uci_to_move(pos, uci)
                    if played is None: break
                    pos.make_move(played)

            if n_in % 100 == 0:
                print(f"  scanned {n_in} games, extracted {n_out} puzzles", file=sys.stderr)

    print(f"done. games scanned={n_in} puzzles={n_out} -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
