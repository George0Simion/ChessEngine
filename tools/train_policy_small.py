"""Train a TINY supervised policy net on (position -> played move) pairs.

This model is OPTIONAL. The engine works without it. We use it only as a
move-ordering / opening-choice prior (see engine/ordering.py if/when wired
through, and engine/book.py for opening variety).

Input data: a JSONL of game records (output of parse_kaggle_games.py with
--no-fens omitted, OR re-derived here).

Model:
    Inputs:  17 planes of 8x8
      - 12 piece planes (P,N,B,R,Q,K * white,black)
      - 1 side-to-move plane (1.0 if STM is white from input perspective)
      - 4 castling-rights planes (constant value)
    Output:  64*64 = 4096 logits over (from, to) pairs (promotions collapsed to
             their underlying move; the engine handles promotion choice).

We always present the board from the side-to-move's perspective (mirror
vertically for black) so the model only ever sees "us at bottom".

Usage:
    python -m tools.train_policy_small --in data/games.jsonl --out models/policy.pt
        [--epochs 2] [--batch 128] [--lr 1e-3] [--max-positions 200000]
"""

from __future__ import annotations
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine.board import Position
from engine.types import (
    FEN_START, WHITE, BLACK, NO_PIECE, sq, file_of, rank_of, square_from_name,
    PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING,
    WK_CASTLE, WQ_CASTLE, BK_CASTLE, BQ_CASTLE,
    piece_type, piece_color,
)
from engine.movegen import generate_moves


def _mirror_sq(s: int) -> int:
    return sq(file_of(s), 7 - rank_of(s))


def encode_position(pos: Position):
    """Return (planes [17, 8, 8] as flat list, length 17*64).

    Convention: always from STM's POV. If STM is black, the board is mirrored
    so the side to move is at the bottom.
    """
    planes = [[0.0] * 64 for _ in range(17)]
    stm = pos.side
    for s in range(64):
        pc = pos.board[s]
        if pc == NO_PIECE:
            continue
        pt = piece_type(pc); c = piece_color(pc)
        # Plane: 0..5 = our pieces (P..K), 6..11 = their pieces.
        if c == stm:
            plane = pt - 1
        else:
            plane = 6 + (pt - 1)
        if stm == BLACK:
            planes[plane][_mirror_sq(s)] = 1.0
        else:
            planes[plane][s] = 1.0

    # Side-to-move plane (constant 1.0 since we always rotate to STM's POV).
    for i in range(64):
        planes[12][i] = 1.0

    # Castling rights planes
    rights = pos.castling
    our_K  = (WK_CASTLE if stm == WHITE else BK_CASTLE)
    our_Q  = (WQ_CASTLE if stm == WHITE else BQ_CASTLE)
    their_K = (BK_CASTLE if stm == WHITE else WK_CASTLE)
    their_Q = (BQ_CASTLE if stm == WHITE else WQ_CASTLE)
    if rights & our_K:
        for i in range(64): planes[13][i] = 1.0
    if rights & our_Q:
        for i in range(64): planes[14][i] = 1.0
    if rights & their_K:
        for i in range(64): planes[15][i] = 1.0
    if rights & their_Q:
        for i in range(64): planes[16][i] = 1.0

    return planes


def encode_move_label(frm: int, to: int, side: int) -> int:
    """Return a (from,to) integer label in 0..4095, in STM-relative coords."""
    if side == BLACK:
        frm = _mirror_sq(frm)
        to  = _mirror_sq(to)
    return frm * 64 + to


def iter_training_examples(jsonl_path: str, max_positions: int):
    """Yield (planes, label) tuples."""
    n = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            moves = rec.get("moves_uci") or []
            if not moves:
                continue
            pos = Position.from_fen(FEN_START)
            from engine.types import move_from, move_to, move_promo
            from engine.types import KNIGHT, BISHOP, ROOK, QUEEN
            for uci in moves:
                # Translate UCI into our move format to apply
                try:
                    frm = square_from_name(uci[0:2])
                    to  = square_from_name(uci[2:4])
                except Exception:
                    break
                promo_ch = uci[4] if len(uci) >= 5 else None
                promo_pt = {"n": KNIGHT, "b": BISHOP, "r": ROOK, "q": QUEEN}.get(promo_ch, 0)
                # Find legal match
                found = None
                for m in generate_moves(pos):
                    if move_from(m) == frm and move_to(m) == to:
                        if promo_pt and move_promo(m) != promo_pt:
                            continue
                        if (not promo_pt) and move_promo(m):
                            continue
                        found = m
                        break
                if found is None:
                    break

                planes = encode_position(pos)
                label  = encode_move_label(frm, to, pos.side)
                yield planes, label
                n += 1
                if max_positions and n >= max_positions:
                    return
                pos.make_move(found)


def main() -> None:
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
    except ImportError:
        print("PyTorch is required for this tool. Install with: pip install torch", file=sys.stderr)
        sys.exit(1)

    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--max-positions", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    random.seed(args.seed)

    # Collect data into tensors (small dataset by design).
    print("collecting training examples...", file=sys.stderr)
    X, Y = [], []
    for planes, label in iter_training_examples(args.src, args.max_positions):
        X.append(planes)
        Y.append(label)
    if not X:
        print("no training data found.", file=sys.stderr)
        sys.exit(2)
    print(f"collected {len(X)} positions", file=sys.stderr)

    X_t = torch.tensor(X, dtype=torch.float32).view(-1, 17, 8, 8)
    Y_t = torch.tensor(Y, dtype=torch.long)

    # Train/val split.
    n = X_t.size(0)
    perm = torch.randperm(n)
    X_t, Y_t = X_t[perm], Y_t[perm]
    split = max(1, int(n * 0.9))
    X_tr, Y_tr = X_t[:split], Y_t[:split]
    X_va, Y_va = X_t[split:], Y_t[split:]

    class TinyPolicy(nn.Module):
        def __init__(self):
            super().__init__()
            self.c1 = nn.Conv2d(17, 32, 3, padding=1)
            self.c2 = nn.Conv2d(32, 48, 3, padding=1)
            self.c3 = nn.Conv2d(48, 48, 3, padding=1)
            self.fc = nn.Linear(48 * 8 * 8, 4096)

        def forward(self, x):
            x = F.relu(self.c1(x))
            x = F.relu(self.c2(x))
            x = F.relu(self.c3(x))
            x = x.view(x.size(0), -1)
            return self.fc(x)

    model = TinyPolicy()
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.CrossEntropyLoss()

    for epoch in range(args.epochs):
        model.train()
        perm = torch.randperm(X_tr.size(0))
        running = 0.0
        steps = 0
        for i in range(0, X_tr.size(0), args.batch):
            idx = perm[i:i + args.batch]
            xb, yb = X_tr[idx], Y_tr[idx]
            opt.zero_grad()
            logits = model(xb)
            loss = loss_fn(logits, yb)
            loss.backward()
            opt.step()
            running += float(loss.item())
            steps += 1
        # Validation
        model.eval()
        with torch.no_grad():
            preds = model(X_va).argmax(dim=1)
            acc = (preds == Y_va).float().mean().item() if X_va.numel() > 0 else 0.0
        print(f"epoch {epoch+1} loss={running/max(1,steps):.4f} val_top1={acc:.3f}",
              file=sys.stderr)

    os.makedirs(os.path.dirname(args.dst) or ".", exist_ok=True)
    torch.save(model.state_dict(), args.dst)
    print(f"saved tiny policy to {args.dst}", file=sys.stderr)


if __name__ == "__main__":
    main()
