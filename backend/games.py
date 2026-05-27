"""Flask blueprint for bot games.

Endpoints (all require Authorization: Bearer <jwt>):

    POST /games/bot                 - create a new bot game
    GET  /games/<game_id>           - read state
    POST /games/<game_id>/move      - submit a move (auto-plays the bot's reply)
    POST /games/<game_id>/resign    - resign the game
"""

from __future__ import annotations
import random
from datetime import datetime
from typing import Optional, Tuple

from flask import Blueprint, request, jsonify

from auth import token_required
from models import db, Game

from backend import engine_client


games_bp = Blueprint('games', __name__, url_prefix='/games')


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FEN_START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
VALID_LEVELS = {1, 2, 3, 4}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _side_to_move(fen: str) -> str:
    """Extract the side-to-move from a FEN (w/b -> 'white'/'black')."""
    parts = fen.split()
    if len(parts) < 2:
        return "white"
    return "white" if parts[1] == "w" else "black"


def _user_color_for(game: Game, user_id: int) -> Optional[str]:
    """Return 'white' / 'black' if the user occupies a side in `game`, else None."""
    if game.white_id == user_id and not game.white_is_bot:
        return "white"
    if game.black_id == user_id and not game.black_is_bot:
        return "black"
    return None


def _is_bot_turn(game: Game) -> bool:
    stm = _side_to_move(game.current_fen)
    if stm == "white" and game.white_is_bot:
        return True
    if stm == "black" and game.black_is_bot:
        return True
    return False


def _moves_list(game: Game) -> list:
    if not game.moves_history:
        return []
    return game.moves_history.split()


def _append_move(game: Game, uci: str) -> None:
    game.moves_history = (game.moves_history + " " + uci).strip()


def _serialize(game: Game, last_bot_move: Optional[str] = None,
                user_color: Optional[str] = None) -> dict:
    """Standard game-state JSON payload."""
    payload = {
        "game_id": game.id,
        "fen": game.current_fen,
        "moves": _moves_list(game),
        "status": game.status,
        "result_reason": game.result_reason,
        "white_is_bot": bool(game.white_is_bot),
        "black_is_bot": bool(game.black_is_bot),
        "bot_level": game.bot_level,
        "created_at": game.created_at.isoformat() if game.created_at else None,
        "updated_at": game.updated_at.isoformat() if game.updated_at else None,
    }
    if last_bot_move is not None:
        payload["last_bot_move"] = last_bot_move
    if user_color is not None:
        payload["user_color"] = user_color
    return payload


def _terminal_status_for_side(status: str, mover_color: str) -> Tuple[str, Optional[str]]:
    """Translate an engine.api status (post-move) + the color that JUST moved
    into our (game.status, game.result_reason) pair.

    `status` is one of: active | checkmate | stalemate | draw.
    Checkmate => the side that just moved wins.
    """
    if status == "checkmate":
        return ("white_win" if mover_color == "white" else "black_win"), "checkmate"
    if status == "stalemate":
        return "draw", "stalemate"
    if status == "draw":
        return "draw", "draw"
    return "active", None


def _detect_threefold(moves: list) -> bool:
    """Replay the game and check whether the CURRENT position has appeared
    3+ times. Uses the engine's own Position to get accurate zobrist matching.
    """
    # Local import to avoid pulling engine into module load if it ever moves.
    from engine.board import Position
    from engine.api import _uci_to_engine_move

    pos = Position.from_fen(FEN_START)
    for uci in moves:
        m = _uci_to_engine_move(pos, uci)
        if m == 0:
            return False
        pos.make_move(m)
    return pos.is_threefold()


# ---------------------------------------------------------------------------
# Endpoint: create a new bot game
# ---------------------------------------------------------------------------
@games_bp.post('/bot')
@token_required
def create_bot_game(current_user):
    data = request.get_json(silent=True) or {}
    color = (data.get("color") or "white").strip().lower()
    level = data.get("level", 3)
    try:
        level = int(level)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "level must be an integer 1..4"}), 400
    if level not in VALID_LEVELS:
        return jsonify({"ok": False, "error": "level must be 1, 2, 3 or 4"}), 400
    if color not in {"white", "black", "random"}:
        return jsonify({"ok": False, "error": "color must be white|black|random"}), 400

    if color == "random":
        color = random.choice(("white", "black"))

    # Build the game row.
    game = Game(
        current_fen=FEN_START,
        moves_history="",
        status="active",
        bot_level=level,
    )
    if color == "white":
        game.white_id = current_user.id
        game.white_is_bot = False
        game.black_id = None
        game.black_is_bot = True
    else:
        game.black_id = current_user.id
        game.black_is_bot = False
        game.white_id = None
        game.white_is_bot = True

    db.session.add(game)
    db.session.flush()  # assign game.id

    # If the bot is white, let it play the first move immediately.
    if game.white_is_bot:
        bot = engine_client.get_bot_move(game.current_fen, level=level)
        if bot["ok"] and bot["move"]:
            applied = engine_client.apply_user_move(game.current_fen, bot["move"])
            if applied["ok"]:
                _append_move(game, bot["move"])
                game.current_fen = applied["fen"]
                game.status, game.result_reason = _terminal_status_for_side(
                    applied["status"], "white",
                )

    game.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "ok": True,
        **_serialize(game, user_color=color),
    }), 201


# ---------------------------------------------------------------------------
# Endpoint: get game state
# ---------------------------------------------------------------------------
@games_bp.get('/<int:game_id>')
@token_required
def get_game(current_user, game_id):
    game = Game.query.get(game_id)
    if not game:
        return jsonify({"ok": False, "error": "game not found"}), 404

    user_color = _user_color_for(game, current_user.id)
    if user_color is None:
        return jsonify({"ok": False, "error": "not your game"}), 403

    return jsonify({"ok": True, **_serialize(game, user_color=user_color)})


# ---------------------------------------------------------------------------
# Endpoint: submit a move
# ---------------------------------------------------------------------------
@games_bp.post('/<int:game_id>/move')
@token_required
def submit_move(current_user, game_id):
    data = request.get_json(silent=True) or {}
    uci = (data.get("move") or "").strip().lower()
    if not uci:
        return jsonify({"ok": False, "error": "missing 'move'"}), 400

    game = Game.query.get(game_id)
    if not game:
        return jsonify({"ok": False, "error": "game not found"}), 404

    user_color = _user_color_for(game, current_user.id)
    if user_color is None:
        return jsonify({"ok": False, "error": "not your game"}), 403

    if game.status != "active":
        return jsonify({
            "ok": False, "error": "game is not active",
            **_serialize(game, user_color=user_color),
        }), 400

    stm = _side_to_move(game.current_fen)
    if stm != user_color:
        return jsonify({
            "ok": False, "error": "not your turn",
            **_serialize(game, user_color=user_color),
        }), 400

    # Validate + apply the user's move via the in-house engine.
    applied = engine_client.apply_user_move(game.current_fen, uci)
    if not applied["ok"]:
        return jsonify({
            "ok": False, "error": applied.get("error", "illegal move"),
            **_serialize(game, user_color=user_color),
        }), 400

    _append_move(game, uci)
    game.current_fen = applied["fen"]
    game.status, game.result_reason = _terminal_status_for_side(
        applied["status"], user_color,
    )

    # Threefold check (engine.api.apply_move doesn't see history).
    if game.status == "active" and _detect_threefold(_moves_list(game)):
        game.status = "draw"
        game.result_reason = "draw_threefold"

    last_bot_move: Optional[str] = None

    # If still active and it's the bot's turn, let the bot reply.
    if game.status == "active" and _is_bot_turn(game):
        bot = engine_client.get_bot_move(
            game.current_fen, level=game.bot_level or 3,
        )
        if not bot["ok"]:
            # Engine error — fail soft: keep user move but flag the game as aborted.
            game.status = "aborted"
            game.result_reason = "engine_error"
        elif bot["move"] is None:
            # No legal moves for the bot: terminal position right after user's move
            # (already handled above as checkmate/stalemate). This is a defensive
            # branch in case the bot was asked to play in a drawn position.
            pass
        else:
            bot_applied = engine_client.apply_user_move(game.current_fen, bot["move"])
            if not bot_applied["ok"]:
                # Engine returned an illegal move — hard guard.
                game.status = "aborted"
                game.result_reason = "engine_illegal_move"
            else:
                _append_move(game, bot["move"])
                game.current_fen = bot_applied["fen"]
                last_bot_move = bot["move"]
                bot_color = "white" if game.white_is_bot else "black"
                game.status, game.result_reason = _terminal_status_for_side(
                    bot_applied["status"], bot_color,
                )
                if game.status == "active" and _detect_threefold(_moves_list(game)):
                    game.status = "draw"
                    game.result_reason = "draw_threefold"

    # Set winner string for backwards compat.
    if game.status == "white_win":
        game.winner = "white"
    elif game.status == "black_win":
        game.winner = "black"
    elif game.status == "draw":
        game.winner = None

    game.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        "ok": True,
        **_serialize(game, last_bot_move=last_bot_move, user_color=user_color),
    })


# ---------------------------------------------------------------------------
# Endpoint: resign
# ---------------------------------------------------------------------------
@games_bp.post('/<int:game_id>/resign')
@token_required
def resign(current_user, game_id):
    game = Game.query.get(game_id)
    if not game:
        return jsonify({"ok": False, "error": "game not found"}), 404

    user_color = _user_color_for(game, current_user.id)
    if user_color is None:
        return jsonify({"ok": False, "error": "not your game"}), 403
    if game.status != "active":
        return jsonify({
            "ok": False, "error": "game is not active",
            **_serialize(game, user_color=user_color),
        }), 400

    # User loses; opponent wins.
    game.status = "black_win" if user_color == "white" else "white_win"
    game.winner = "black" if user_color == "white" else "white"
    game.result_reason = "resignation"
    game.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"ok": True, **_serialize(game, user_color=user_color)})
