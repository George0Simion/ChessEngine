"""Opening book.

Book file (JSON), produced by `tools/build_opening_book.py`:

    {
      "<zobrist_hex>": [
        ["e2e4", 1234, 1750],   # uci, frequency, avg_rating
        ...
      ],
      ...
    }

The engine works fine without a book — `probe` simply returns `None`.

Selection blends frequency and rating:
    quality(uci) = freq * rating_factor(rating, baseline=1500)

`randomness` in [0, 1] biases the pick toward variety. 0 means "always best",
~1 means "sample roughly proportional to quality".
"""

from __future__ import annotations
import json
import math
import os
import random
from typing import Optional, Dict, List, Tuple

from .board import Position
from .movegen import generate_moves
from .types import move_to_uci


_BOOK: Optional[Dict[str, list]] = None
_BOOK_PATH: Optional[str] = None


def load_book(path: Optional[str] = None) -> None:
    """Load (or reload) the book from `path`. If None, try default locations."""
    global _BOOK, _BOOK_PATH
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "..", "data", "opening_book.json"),
            os.path.join(here, "opening_book.json"),
        ]
        for c in candidates:
            if os.path.exists(c):
                path = c
                break
    if path is None or not os.path.exists(path):
        _BOOK = None
        _BOOK_PATH = None
        return
    with open(path, "r", encoding="utf-8") as f:
        _BOOK = json.load(f)
    _BOOK_PATH = path


def _quality(freq: int, rating: int, baseline: int = 1500) -> float:
    """Higher = stronger book move. Frequency-weighted, rating-tilted."""
    rating_factor = 1.0 + max(0, rating - baseline) / 400.0
    return max(1.0, float(freq)) * rating_factor


def probe(pos: Position, rng: Optional[random.Random] = None,
          min_freq: int = 1, randomness: float = 0.0) -> Optional[int]:
    """Return a book move for this position, or None.

    `randomness` in [0, 1]:
      0.0 -> deterministic, pick the highest-quality move
      ~1.0 -> sample roughly proportional to quality
    """
    global _BOOK
    if _BOOK is None:
        load_book()
    if not _BOOK:
        return None

    key = format(pos.zobrist, "x")
    entries = _BOOK.get(key)
    if not entries:
        return None

    legal = {move_to_uci(m): m for m in generate_moves(pos)}

    # Build (uci, move, quality) for legal book entries above min_freq.
    candidates: List[Tuple[str, int, float]] = []
    for row in entries:
        uci = row[0]
        freq = row[1] if len(row) > 1 else 1
        rating = row[2] if len(row) > 2 else 1500
        if freq < min_freq:
            continue
        m = legal.get(uci)
        if m is None:
            continue
        candidates.append((uci, m, _quality(freq, rating)))

    if not candidates:
        return None

    if randomness <= 0.0:
        candidates.sort(key=lambda t: -t[2])
        return candidates[0][1]

    if rng is None:
        rng = random.Random()

    # Soften / sharpen weights with `randomness`.
    # `temperature = max(0.1, randomness)` — lower = sharper toward best.
    temperature = max(0.1, randomness)
    # Use exp-based weighting on log-quality for numerical sanity.
    weights = []
    for (_, _, q) in candidates:
        weights.append(math.exp(math.log(q) / temperature))
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for (_, m, _), w in zip(candidates, weights):
        acc += w
        if r <= acc:
            return m
    return candidates[-1][1]
