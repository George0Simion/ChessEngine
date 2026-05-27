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


def set_game_result(game_id: int, status: str, winner: Optional[str]) -> None:
    with SessionLocal() as session:
        game = session.get(Game, game_id)
        if not game:
            return
        game.status = status
        game.winner = winner
        session.commit()
