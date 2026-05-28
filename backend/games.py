"""Flask blueprint for bot games.

Endpoints (all require Authorization: Bearer <jwt>):

    POST /games/bot                  - create a new bot game
    GET  /games/<game_id>            - read state
    POST /games/<game_id>/move       - submit a move (auto-plays the bot's reply)
    POST /games/<game_id>/resign     - resign the game
    GET  /games/history              - list user's games (newest first)
    POST /games/record               - persist a finished legacy bot game
    GET  /games/<game_id>/review-data  - moves + FENs for replay UI
    POST /games/<game_id>/analyze    - run engine analysis on every ply
    GET  /games/<game_id>/analysis   - return cached analysis if present
"""

from __future__ import annotations
import json
import os
import random
from datetime import datetime
from typing import Optional, Tuple

from flask import Blueprint, current_app, request, jsonify

from auth import token_required
from models import db, Game, User

from backend import engine_client


games_bp = Blueprint('games', __name__, url_prefix='/games')


BOT_NAMES = {
    1: "Andreea Botez",
    2: "Anna Cramling",
    3: "GothamChess",
    4: "Magnus Carlsen",
}


def _analysis_path(game_id: int) -> str:
    """Path to the cached analysis JSON for `game_id`."""
    instance_dir = current_app.instance_path if current_app else "instance"
    dir_path = os.path.join(instance_dir, "analyses")
    os.makedirs(dir_path, exist_ok=True)
    return os.path.join(dir_path, f"{game_id}.json")


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
    """Return the game's UCI moves as a list.

    Bot games store moves space-separated; the multiplayer flow stores them
    comma-separated. Normalize both so review/history always see every move.
    """
    raw = game.moves_history or ""
    if not raw.strip():
        return []
    return raw.replace(",", " ").split()


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
@games_bp.get('/history')
@token_required
def history(current_user):
    """Return the authenticated user's persisted games (bot + online).
    Excludes puzzle attempts, which are not stored in the games table."""
    rows = (Game.query
            .filter((Game.white_id == current_user.id) |
                    (Game.black_id == current_user.id))
            .order_by(Game.created_at.desc())
            .limit(100)
            .all())

    # Pre-fetch all opponent usernames in one query.
    opp_ids = set()
    for g in rows:
        is_white = (g.white_id == current_user.id)
        opp_id = g.black_id if is_white else g.white_id
        if opp_id is not None:
            opp_ids.add(opp_id)
    usernames = {}
    if opp_ids:
        for u in User.query.filter(User.id.in_(opp_ids)).all():
            usernames[u.id] = u.username

    out = []
    for g in rows:
        user_color = "white" if g.white_id == current_user.id else "black"
        opp_is_bot = g.black_is_bot if user_color == "white" else g.white_is_bot
        opp_id = g.black_id if user_color == "white" else g.white_id
        if opp_is_bot:
            opponent = BOT_NAMES.get(g.bot_level or 3, "Magnus Carlsen")
            mode = "bot"
        else:
            opponent = usernames.get(opp_id) or "Online"
            mode = "online"

        if g.status == "active":
            result = "in_progress"
        elif g.status == "draw":
            result = "draw"
        elif g.status == "aborted":
            result = "aborted"
        elif g.status == f"{user_color}_win":
            result = "win"
        else:
            result = "loss"

        moves = (g.moves_history or "").split()
        analysis_ready = os.path.isfile(_analysis_path(g.id))

        out.append({
            "id":             g.id,
            "mode":           mode,
            "opponent":       opponent,
            "user_color":     user_color,
            "status":         g.status,
            "result":         result,
            "result_reason":  g.result_reason,
            "moves_count":    len(moves),
            "moves":          moves,
            "bot_level":      g.bot_level,
            "analysis_ready": bool(analysis_ready),
            "created_at":     g.created_at.isoformat() if g.created_at else None,
            "updated_at":     g.updated_at.isoformat() if g.updated_at else None,
        })

    return jsonify({"ok": True, "games": out})


@games_bp.post('/record')
@token_required
def record(current_user):
    """Persist a finished bot game played via the legacy /api/* flow.

    The unified play page uses session-based legacy endpoints (so guests can
    play). When the player is authenticated and a bot game ends, the frontend
    posts the final outcome here so it shows up in their /games/history.
    """
    data = request.get_json(silent=True) or {}
    color = (data.get("color") or "").strip().lower()
    if color not in {"white", "black"}:
        return jsonify({"ok": False, "error": "invalid color"}), 400

    try:
        bot_level = int(data.get("bot_level")) if data.get("bot_level") else None
    except (TypeError, ValueError):
        bot_level = None

    status = (data.get("status") or "active").strip()
    reason = data.get("result_reason")
    moves = data.get("moves") or []
    fen = data.get("fen") or FEN_START

    if not isinstance(moves, list):
        moves = []

    g = Game(
        current_fen=fen,
        moves_history=" ".join(moves),
        status=status,
        result_reason=reason,
        bot_level=bot_level,
    )
    if color == "white":
        g.white_id = current_user.id
        g.white_is_bot = False
        g.black_is_bot = True
    else:
        g.black_id = current_user.id
        g.black_is_bot = False
        g.white_is_bot = True

    if status == "white_win":
        g.winner = "white"
    elif status == "black_win":
        g.winner = "black"

    g.updated_at = datetime.utcnow()
    db.session.add(g)
    db.session.commit()

    return jsonify({"ok": True, "game_id": g.id}), 201


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


# ---------------------------------------------------------------------------
# Review & Analysis
# ---------------------------------------------------------------------------
def _game_player_names(game: Game) -> Tuple[str, str]:
    """Return (white_name, black_name) for display."""
    white = "White"
    black = "Black"
    if game.white_is_bot:
        white = BOT_NAMES.get(game.bot_level or 3, "Bot")
    elif game.white_id is not None:
        u = User.query.get(game.white_id)
        if u:
            white = u.username
    if game.black_is_bot:
        black = BOT_NAMES.get(game.bot_level or 3, "Bot")
    elif game.black_id is not None:
        u = User.query.get(game.black_id)
        if u:
            black = u.username
    return white, black


def _replay_game(moves: list) -> dict:
    """Replay UCI moves through ChessGame to capture FENs + SANs for each ply."""
    from chessmate.core import ChessGame, InvalidMoveError
    game = ChessGame()
    starting_fen = game.to_fen()
    plies = []
    for i, uci in enumerate(moves):
        if not uci or len(uci) < 4:
            continue
        origin, target = uci[:2], uci[2:4]
        promo_ch = uci[4] if len(uci) >= 5 else None
        promo_kind = {"q": "queen", "r": "rook", "b": "bishop", "n": "knight"}.get(promo_ch)
        fen_before = game.to_fen()
        color = game.turn
        try:
            game.move(origin, target, promotion=promo_kind)
        except InvalidMoveError as e:
            return {
                "ok": False, "error": f"Move {i+1} ({uci}): {e}",
                "starting_fen": starting_fen, "plies": plies,
            }
        rec = game.history[-1]
        plies.append({
            "ply":         i + 1,
            "color":       color,
            "uci":         uci,
            "san":         rec.san,
            "fen_before":  fen_before,
            "fen_after":   game.to_fen(),
        })
    return {"ok": True, "starting_fen": starting_fen, "plies": plies}


@games_bp.get('/<int:game_id>/review-data')
@token_required
def review_data(current_user, game_id):
    game = Game.query.get(game_id)
    if not game:
        return jsonify({"ok": False, "error": "game not found"}), 404
    user_color = _user_color_for(game, current_user.id)
    if user_color is None:
        return jsonify({"ok": False, "error": "not your game"}), 403

    moves = _moves_list(game)
    replay = _replay_game(moves)
    white_name, black_name = _game_player_names(game)

    return jsonify({
        "ok": replay["ok"],
        "error": replay.get("error"),
        "meta": {
            "id":            game.id,
            "mode":          "bot" if (game.white_is_bot or game.black_is_bot) else "online",
            "white_name":    white_name,
            "black_name":    black_name,
            "user_color":    user_color,
            "status":        game.status,
            "result_reason": game.result_reason,
            "bot_level":     game.bot_level,
            "created_at":    game.created_at.isoformat() if game.created_at else None,
        },
        "starting_fen":   replay["starting_fen"],
        "plies":          replay["plies"],
        "analysis_ready": os.path.isfile(_analysis_path(game_id)),
    })


@games_bp.post('/replay')
def replay_adhoc():
    """Stateless replay for games that are NOT persisted (e.g. local 1v1).

    Body: { "moves": ["e2e4", ...], "meta": { ...optional display fields } }
    Returns the same shape as /review-data so the review page can render it.
    No auth: local games can be played by guests.
    """
    data = request.get_json(silent=True) or {}
    moves = data.get("moves") or []
    if not isinstance(moves, list):
        return jsonify({"ok": False, "error": "moves must be a list"}), 400
    meta_in = data.get("meta") or {}

    replay = _replay_game([str(m) for m in moves])
    return jsonify({
        "ok": replay["ok"],
        "error": replay.get("error"),
        "meta": {
            "id":            None,
            "mode":          "local",
            "white_name":    meta_in.get("white_name") or "White",
            "black_name":    meta_in.get("black_name") or "Black",
            "user_color":    meta_in.get("user_color") or "white",
            "status":        meta_in.get("status") or "",
            "result_reason": meta_in.get("result_reason"),
            "bot_level":     None,
            "created_at":    None,
        },
        "starting_fen": replay["starting_fen"],
        "plies":        replay["plies"],
        "analysis_ready": False,
    })


@games_bp.post('/replay/analyze')
def analyze_replay_adhoc():
    """Run engine analysis for an unsaved replay.

    Used by local 1v1 games: they are not persisted in the DB, so the review
    page sends the stashed UCI move list back here.
    """
    data = request.get_json(silent=True) or {}
    moves = data.get("moves") or []
    if not isinstance(moves, list):
        return jsonify({"ok": False, "error": "moves must be a list"}), 400
    if not moves:
        return jsonify({"ok": False, "error": "game has no moves"}), 400

    replay = _replay_game([str(m) for m in moves])
    if not replay["ok"]:
        return jsonify({"ok": False, "error": replay.get("error") or "replay failed"}), 400

    return jsonify(_run_analysis(replay["plies"]))


# ---------- Analysis ----------

_CATEGORY_THRESHOLDS = [
    (10,  "Best"),
    (25,  "Excellent"),
    (60,  "Good"),
    (120, "Inaccuracy"),
    (250, "Mistake"),
]


def _categorize(cp_loss: int) -> str:
    for threshold, label in _CATEGORY_THRESHOLDS:
        if cp_loss <= threshold:
            return label
    return "Blunder"


_MATE_LARGE = 30_000


def _eval_to_cp(eval_dict: dict) -> int:
    """Translate `best_move` result (`{score_cp, mate}`) into a comparable cp value.
    Mate scores are clamped to ±_MATE_LARGE so arithmetic doesn't overflow."""
    if eval_dict.get("mate") is not None:
        mate = eval_dict["mate"]
        return _MATE_LARGE - abs(mate) * 10 if mate > 0 else -(_MATE_LARGE - abs(mate) * 10)
    return int(eval_dict.get("score_cp") or 0)


def _material_value(fen: str) -> int:
    val = {"p": 1, "n": 3, "b": 3, "r": 5, "q": 9}
    placement = fen.split()[0]
    score = 0
    for ch in placement:
        lo = ch.lower()
        if lo in val:
            score += val[lo] if ch.isupper() else -val[lo]
    return score


def _is_sacrifice(played_color: str, fen_before: str, fen_after: str) -> bool:
    delta = _material_value(fen_after) - _material_value(fen_before)
    return delta <= -2 if played_color == "white" else delta >= 2


def _run_analysis(plies: list, time_ms: int = 350, max_depth: int = 8) -> dict:
    from engine import api as engine_api

    moves_out = []
    summary = {k: 0 for k in
               ["Best", "Excellent", "Good", "Inaccuracy", "Mistake", "Blunder", "Brilliant"]}

    for p in plies:
        fen_before = p["fen_before"]
        fen_after  = p["fen_after"]
        played_uci = p["uci"]
        color      = p["color"]

        best = engine_api.best_move(
            fen_before, time_ms=time_ms, max_depth=max_depth, use_book=False,
        )
        after_search = engine_api.best_move(
            fen_after, time_ms=max(150, time_ms // 2), max_depth=max_depth,
            use_book=False,
        )

        eval_before = _eval_to_cp(best)
        eval_after_mover = -_eval_to_cp(after_search)
        cp_loss = max(0, eval_before - eval_after_mover)

        if played_uci == best.get("move"):
            category = "Best"
        else:
            category = _categorize(cp_loss)

        best_mate  = best.get("mate")
        after_mate = after_search.get("mate")
        if best_mate is not None and best_mate > 0:
            if played_uci != best.get("move") and (after_mate is None or after_mate >= 0):
                category = "Blunder"
        if after_mate is not None and after_mate < 0 and (best_mate is None or best_mate <= 0):
            category = "Brilliant"

        if (category in ("Best", "Excellent")
                and played_uci != best.get("move")
                and _is_sacrifice(color, fen_before, fen_after)
                and cp_loss <= 25):
            category = "Brilliant"

        summary[category] = summary.get(category, 0) + 1

        moves_out.append({
            "ply":         p["ply"],
            "color":       color,
            "uci":         played_uci,
            "san":         p.get("san", ""),
            "fen_before":  fen_before,
            "fen_after":   fen_after,
            "best_move":   best.get("move"),
            "best_line":   best.get("pv") or [],
            "eval_before": eval_before if abs(eval_before) < _MATE_LARGE - 1000 else None,
            "eval_after":  eval_after_mover if abs(eval_after_mover) < _MATE_LARGE - 1000 else None,
            "cp_loss":     cp_loss if abs(eval_before) < _MATE_LARGE - 1000 else None,
            "mate_before": best_mate,
            "mate_after":  -after_mate if after_mate is not None else None,
            "category":    category,
        })

    return {"ok": True, "moves": moves_out, "summary": summary}


@games_bp.post('/<int:game_id>/analyze')
@token_required
def analyze(current_user, game_id):
    game = Game.query.get(game_id)
    if not game:
        return jsonify({"ok": False, "error": "game not found"}), 404
    if _user_color_for(game, current_user.id) is None:
        return jsonify({"ok": False, "error": "not your game"}), 403

    force = (request.args.get("force") or "").strip() in ("1", "true", "yes")
    cache_path = _analysis_path(game_id)
    if not force and os.path.isfile(cache_path):
        with open(cache_path) as f:
            return jsonify(json.load(f))

    moves = _moves_list(game)
    if not moves:
        return jsonify({"ok": False, "error": "game has no moves"}), 400

    replay = _replay_game(moves)
    if not replay["ok"]:
        return jsonify({"ok": False, "error": replay.get("error") or "replay failed"}), 400

    result = _run_analysis(replay["plies"])
    result["game_id"] = game_id
    with open(cache_path, "w") as f:
        json.dump(result, f)
    return jsonify(result)


@games_bp.get('/<int:game_id>/analysis')
@token_required
def get_analysis(current_user, game_id):
    game = Game.query.get(game_id)
    if not game:
        return jsonify({"ok": False, "error": "game not found"}), 404
    if _user_color_for(game, current_user.id) is None:
        return jsonify({"ok": False, "error": "not your game"}), 403
    cache_path = _analysis_path(game_id)
    if not os.path.isfile(cache_path):
        return jsonify({"ok": False, "error": "not_analyzed_yet"}), 404
    with open(cache_path) as f:
        return jsonify(json.load(f))
