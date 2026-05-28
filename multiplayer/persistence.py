from __future__ import annotations

from typing import Optional

from models import Game

from .db import SessionLocal
from .models import OnlineGame


def create_game_record(
    white_id: int,
    black_id: int,
    room_id: str,
    base_min: int,
    increment_sec: int,
) -> int:
    with SessionLocal() as session:
        game = Game(
            white_id=white_id,
            black_id=black_id,
            status="active",
            winner=None,
            moves_history="",
        )
        session.add(game)
        session.flush()

        online = OnlineGame(
            game_id=game.id,
            room_id=room_id,
            time_base_min=base_min,
            increment_sec=increment_sec,
        )
        session.add(online)
        session.commit()
        return game.id


def append_move(game_id: int, uci: str) -> None:
    with SessionLocal() as session:
        game = session.get(Game, game_id)
        if not game:
            return
        if game.moves_history:
            game.moves_history = f"{game.moves_history},{uci}"
        else:
            game.moves_history = uci
        session.commit()


# Raw ChessGame / room statuses -> (canonical status, result_reason).
# Canonical status matches what /games/history expects:
#   white_win | black_win | draw | aborted
_REASON_BY_RAW = {
    "checkmate":         "checkmate",
    "stalemate":         "stalemate",
    "draw_insufficient": "draw_insufficient",
    "draw_fifty_move":   "draw_50_move",
    "draw_repetition":   "draw_threefold",
    "resign":            "resignation",
    "timeout":           "timeout",
    "abandoned":         "abandoned",
}
_DRAW_RAW = {"stalemate", "draw_insufficient", "draw_fifty_move", "draw_repetition", "draw"}


def _canonical_status(raw: str, winner: Optional[str]) -> str:
    """Translate a raw game/room status into the canonical status the rest of
    the app (history, profile) understands."""
    if raw in _DRAW_RAW:
        return "draw"
    if winner in ("white", "black"):
        return f"{winner}_win"
    if raw in ("white_win", "black_win", "draw", "aborted"):
        return raw
    return "aborted"


def set_game_result(
    game_id: int,
    status: str,
    winner: Optional[str],
    reason: Optional[str] = None,
) -> None:
    with SessionLocal() as session:
        game = session.get(Game, game_id)
        if not game:
            return
        game.status = _canonical_status(status, winner)
        game.winner = winner
        # "game_end" is a generic sentinel from the move flow — derive the real
        # reason from the raw status instead of storing the placeholder.
        derived = _REASON_BY_RAW.get(status)
        game.result_reason = (reason if reason and reason != "game_end" else derived) or derived
        session.commit()
