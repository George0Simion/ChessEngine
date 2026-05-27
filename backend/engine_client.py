"""Thin wrapper around the in-house engine for backend gameplay.

Backend code should never call engine.api directly — it goes through this
module so we can swap implementations later without touching routes.
"""

from __future__ import annotations
from typing import Optional

from engine import api as engine_api


# Default time budget per level (the engine API may clamp these further).
_TIME_BUDGETS = {1: 200, 2: 500, 3: 1000, 4: 1500}


def get_bot_move(fen: str, level: int = 3,
                  time_ms: Optional[int] = None) -> dict:
    """Ask the engine for its best move.

    Returns:
        {
          "move":     "e2e4" | None,         # None when the side has no legal move
          "score_cp": <int> | None,          # None when mate found
          "mate":     <int> | None,          # +N = mating in N for STM, -N for opponent
          "depth":    <int>,
          "pv":       ["e2e4", "e7e5", ...],
          "ok":       bool,
          "source":   "search" | "book" | "fallback" | "terminal" | "error",
          "error":    "<message>"            # only when ok=False
        }
    """
    if not isinstance(level, int) or level < 1 or level > 4:
        level = 3
    budget = time_ms if (time_ms is not None and time_ms > 0) else _TIME_BUDGETS[level]

    try:
        result = engine_api.best_move(
            fen=fen,
            time_ms=budget,
            level=level,
        )
    except ValueError as e:
        return {
            "ok": False, "error": f"invalid FEN: {e}",
            "move": None, "score_cp": None, "mate": None,
            "depth": 0, "pv": [], "source": "error",
        }
    except Exception as e:   # engine bug / timeout / unexpected
        return {
            "ok": False, "error": f"engine error: {e!r}",
            "move": None, "score_cp": None, "mate": None,
            "depth": 0, "pv": [], "source": "error",
        }

    return {
        "ok": True,
        "move": result.get("move"),
        "score_cp": result.get("score_cp"),
        "mate": result.get("mate"),
        "depth": result.get("depth", 0),
        "pv": result.get("pv", []),
        "source": result.get("source", "search"),
    }


def analyze_position(fen: str, depth: int = 8) -> dict:
    """Run a deeper analysis on a position. Wraps engine.api.analyze_position."""
    try:
        return engine_api.analyze_position(fen=fen, depth=depth) | {"ok": True}
    except ValueError as e:
        return {"ok": False, "error": f"invalid FEN: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"engine error: {e!r}"}


def legal_moves(fen: str) -> dict:
    """Return all legal moves in UCI for `fen`."""
    try:
        return {"ok": True, "moves": engine_api.legal_moves(fen)}
    except ValueError as e:
        return {"ok": False, "error": f"invalid FEN: {e}", "moves": []}


def apply_user_move(fen: str, move: str) -> dict:
    """Apply a (user-submitted) UCI move to `fen`.

    Returns the engine.api.apply_move result plus an `ok` flag so callers can
    branch uniformly on success/failure.
    """
    try:
        out = engine_api.apply_move(fen, move)
    except ValueError as e:
        return {"ok": False, "error": f"invalid FEN: {e}",
                "fen": fen, "status": "illegal", "legal": False}
    out["ok"] = out.get("legal", False)
    if not out["ok"]:
        out["error"] = "illegal move"
    return out
