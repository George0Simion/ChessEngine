"""Public Python API.

    best_move(fen, time_ms, max_depth=None, level=1..4) -> dict
    analyze_position(fen, depth) -> dict

Both return JSON-serializable dictionaries (no engine objects leak out).

Levels (strength dial — scales budget and randomness ONLY, never rules):

    1  beginner : ~80 ms, depth cap 2, samples weighted from top moves
    2  casual   : ~250 ms, depth cap 4, light random noise
    3  club     : full `time_ms`, deterministic (default)
    4  strong   : 2x `time_ms`, deterministic + bigger search budget
"""

from __future__ import annotations
import random
from typing import Optional, List, Tuple

from .board import Position
from .search import Searcher, root_move_scores
from .tt import TranspositionTable
from .movegen import generate_moves
from .types import (
    move_from, move_to, move_to_uci, square_name,
    NO_MOVE, MATE, MATE_IN_MAX,
    move_promo, is_promotion,
    square_from_name, KNIGHT, BISHOP, ROOK, QUEEN, FEN_START,
)
from . import book as opening_book


# Shared TT for repeated calls (warm cache, much faster on follow-ups).
_SHARED_TT: Optional[TranspositionTable] = None


def _get_tt() -> TranspositionTable:
    global _SHARED_TT
    if _SHARED_TT is None:
        _SHARED_TT = TranspositionTable(mb=32)
    return _SHARED_TT


# ---------------------------------------------------------------------------
# Level configuration
# ---------------------------------------------------------------------------
def _level_config(level: int, time_ms: int, max_depth: Optional[int]):
    """Return (time_ms, max_depth, randomness, top_k).

    randomness in [0..1]: probability that we sample from the top-K instead of
    just picking the best move. top_k = number of candidate moves considered
    when sampling.
    """
    if level <= 1:
        return min(time_ms, 80),  min(max_depth or 2, 2),  0.55, 4
    if level == 2:
        return min(time_ms, 250), min(max_depth or 4, 4),  0.25, 3
    if level == 3:
        return time_ms,           max_depth,               0.0,  1
    # level >= 4
    return max(time_ms, 500) * 2, max_depth,               0.0,  1


# ---------------------------------------------------------------------------
# Main API
# ---------------------------------------------------------------------------
def best_move(fen: str, time_ms: int = 1000,
              max_depth: Optional[int] = None,
              level: int = 3,
              use_book: bool = True,
              book_randomness: Optional[float] = None,
              rng_seed: Optional[int] = None) -> dict:
    """Choose a move for the position given by `fen`.

    Returns a dict like:
        {
          "move": "e2e4", "from": "e2", "to": "e4", "promotion": None,
          "score_cp": 32, "mate": None,
          "depth": 7, "nodes": 12345, "time_ms": 998,
          "pv": ["e2e4", "e7e5", ...],
          "source": "search" | "book" | "fallback",
          "level": 3,
        }

    The returned move is ALWAYS legal (or `None` only when there is no legal
    move — i.e. checkmate or stalemate).
    """
    rng = random.Random(rng_seed)
    pos = Position.from_fen(fen)

    # Guard: no legal moves -> terminal position.
    legal = generate_moves(pos)
    if not legal:
        return _empty_dict(level)

    eff_time, eff_depth, randomness, top_k = _level_config(level, time_ms, max_depth)

    # Book lookup (level-aware variety).
    if use_book:
        if book_randomness is None:
            book_randomness = {1: 0.7, 2: 0.5, 3: 0.2, 4: 0.0}.get(level, 0.2)
        m = opening_book.probe(pos, rng=rng, randomness=book_randomness)
        if m is not None and m in legal:
            return _move_dict(m, source="book", score_cp=0,
                              depth=0, nodes=0, ms=0, pv=[m], level=level)

    searcher = Searcher(_get_tt())
    result = searcher.search(pos, time_ms=eff_time, max_depth=eff_depth)

    chosen = result.best_move
    chosen_score = result.score
    chosen_pv = result.pv

    # Sanity: search MUST return a legal move. If not (shouldn't happen),
    # fall back to the first legal move so we never crash callers.
    if chosen == NO_MOVE or chosen not in legal:
        chosen = legal[0]
        chosen_score = 0
        chosen_pv = [chosen]
        source = "fallback"
    else:
        source = "search"

    # Level-driven randomness: weighted sampling from top-K candidates.
    if randomness > 0 and rng.random() < randomness and len(legal) > 1:
        candidates = _gather_top_candidates(pos, eff_time, eff_depth, top_k)
        if candidates:
            sampled = _weighted_pick(candidates, rng)
            if sampled in legal:
                chosen = sampled
                chosen_pv = [chosen]
                source = "search"

    # Score / mate decode.
    cp = chosen_score
    mate_in = None
    if abs(chosen_score) > MATE_IN_MAX:
        plies_to_mate = MATE - abs(chosen_score)
        mate_in = ((plies_to_mate + 1) // 2) * (1 if chosen_score > 0 else -1)
        cp = None

    return _move_dict(
        chosen, source=source, score_cp=cp, mate=mate_in,
        depth=result.depth, nodes=result.nodes, ms=result.ms,
        pv=chosen_pv, level=level,
    )


def analyze_position(fen: str, depth: int = 8) -> dict:
    """Fixed-depth analysis with a generous safety budget (60 s cap)."""
    pos = Position.from_fen(fen)
    searcher = Searcher(_get_tt())
    result = searcher.search(pos, time_ms=60_000, max_depth=depth)

    cp = result.score
    mate_in = None
    if abs(result.score) > MATE_IN_MAX:
        plies_to_mate = MATE - abs(result.score)
        mate_in = ((plies_to_mate + 1) // 2) * (1 if result.score > 0 else -1)
        cp = None

    return {
        "fen": fen,
        "best": move_to_uci(result.best_move) if result.best_move else None,
        "score_cp": cp,
        "mate": mate_in,
        "depth": result.depth,
        "nodes": result.nodes,
        "time_ms": result.ms,
        "pv": [move_to_uci(m) for m in result.pv],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _gather_top_candidates(pos: Position, time_ms: int, max_depth: Optional[int],
                            top_k: int) -> List[Tuple[int, int]]:
    """Return (score, move) for the top-K legal moves at this budget."""
    scored = root_move_scores(pos, _get_tt(), time_ms=time_ms,
                               max_depth=max_depth)
    if not scored:
        return []
    return scored[: max(1, top_k)]


def _weighted_pick(candidates: List[Tuple[int, int]],
                   rng: random.Random) -> int:
    """Pick a move proportional to softmax-like weights of the score gaps."""
    if not candidates:
        return NO_MOVE
    top_score = candidates[0][0]
    weights = []
    for sc, _ in candidates:
        diff = max(0, top_score - sc)
        # Score-gap → softer weight. 1.0 for the top, decays with gap.
        weights.append(max(0.01, 1.0 / (1.0 + diff / 50.0)))
    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for (_, m), w in zip(candidates, weights):
        acc += w
        if r <= acc:
            return m
    return candidates[-1][1]


# ---------------------------------------------------------------------------
# Position helpers (used by backend gameplay code)
# ---------------------------------------------------------------------------
def _uci_to_engine_move(pos: Position, uci: str) -> int:
    """Translate a UCI string into our packed move format if legal, else NO_MOVE."""
    uci = (uci or "").strip().lower()
    if len(uci) < 4:
        return NO_MOVE
    try:
        frm = square_from_name(uci[0:2])
        to  = square_from_name(uci[2:4])
    except ValueError:
        return NO_MOVE
    promo_ch = uci[4] if len(uci) >= 5 else None
    promo_pt = {"n": KNIGHT, "b": BISHOP, "r": ROOK, "q": QUEEN}.get(promo_ch, 0)
    for m in generate_moves(pos):
        if move_from(m) != frm or move_to(m) != to:
            continue
        if promo_pt and move_promo(m) != promo_pt:
            continue
        if (not promo_pt) and move_promo(m):
            continue
        return m
    return NO_MOVE


def _game_status(pos: Position) -> str:
    """Return one of: active | checkmate | stalemate | draw.

    Note: `draw` here only catches 50-move + insufficient material when called
    with a position built from FEN alone (no move history is available, so
    threefold cannot be detected here). Backend code can do its own threefold
    detection from the persisted move list if needed.
    """
    moves = generate_moves(pos)
    if not moves:
        return "checkmate" if pos.in_check() else "stalemate"
    if pos.is_fifty_move() or pos.insufficient_material():
        return "draw"
    return "active"


def legal_moves(fen: str) -> list:
    """Return all legal UCI moves for the position in `fen`.

    Raises ValueError on malformed FEN.
    """
    pos = Position.from_fen(fen)
    return [move_to_uci(m) for m in generate_moves(pos)]


def apply_move(fen: str, move: str) -> dict:
    """Apply `move` (UCI) to `fen` and return:

        {
          "fen":     "<new FEN>" | "<original FEN if illegal>",
          "status":  "active" | "checkmate" | "stalemate" | "draw" | "illegal",
          "legal":   bool,
          "side_to_move": "white" | "black"   # after the move (if legal)
        }

    Never raises on illegal moves; surfaces them via `legal: False`. Bad FENs
    still raise ValueError — those are programmer errors, not move errors.
    """
    pos = Position.from_fen(fen)
    m = _uci_to_engine_move(pos, move)
    if m == NO_MOVE:
        return {
            "fen": fen,
            "status": "illegal",
            "legal": False,
            "side_to_move": "white" if pos.side == 0 else "black",
        }
    pos.make_move(m)
    status = _game_status(pos)
    return {
        "fen": pos.to_fen(),
        "status": status,
        "legal": True,
        "side_to_move": "white" if pos.side == 0 else "black",
    }


# ---------------------------------------------------------------------------
# Internal helpers (continued)
# ---------------------------------------------------------------------------
def _empty_dict(level: int) -> dict:
    return {
        "move": None, "from": None, "to": None, "promotion": None,
        "score_cp": None, "mate": None,
        "depth": 0, "nodes": 0, "time_ms": 0,
        "pv": [], "source": "terminal", "level": level,
    }


def _move_dict(m: int, *, source: str, score_cp=None, mate=None,
                depth: int = 0, nodes: int = 0, ms: int = 0,
                pv=None, level: int = 3) -> dict:
    if not m or m == NO_MOVE:
        d = _empty_dict(level)
        d["source"] = source
        d["time_ms"] = ms
        return d
    promo = None
    if is_promotion(m):
        promo = "nbrq"[move_promo(m) - 2]
    return {
        "move": move_to_uci(m),
        "from": square_name(move_from(m)),
        "to": square_name(move_to(m)),
        "promotion": promo,
        "score_cp": score_cp,
        "mate": mate,
        "depth": depth,
        "nodes": nodes,
        "time_ms": ms,
        "pv": [move_to_uci(x) for x in (pv or [])],
        "source": source,
        "level": level,
    }
