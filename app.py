from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

from chessmate import ChessGame, InvalidMoveError, build_engine
from chessmate.engine import Engine
from models import db, User, Rating, Game
from flask_migrate import Migrate
from auth import auth_bp


MODE_LOCAL = "local"      # 1v1 hot-seat
MODE_VS_BOT = "vs_bot"    # human vs engine

VALID_MODES = {MODE_LOCAL, MODE_VS_BOT}


@dataclass
class GameSession:
    """Lightweight container for everything that defines the current
    seat assignment. Lives at app scope (single-game server)."""

    game: ChessGame
    mode: str = MODE_LOCAL
    bot_color: Optional[str] = None      # "white" / "black" / None
    engine_name: str = "mcts"
    engine: Optional[Engine] = None

    def mode_info(self) -> dict:
        return {
            "mode": self.mode,
            "botColor": self.bot_color,
            "engine": self.engine_name if self.mode == MODE_VS_BOT else None,
        }


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    # ------------------------------------------------------------------ Config
    db_url = os.environ.get("DATABASE_URL", "sqlite:///chessmate.db")
    # Heroku/Render use postgres:// but SQLAlchemy 1.4+ needs postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "dev-secret-change-in-production"
    )

    db.init_app(app)
    Migrate(app, db)
    app.register_blueprint(auth_bp)

    # Auto-create tables in development (migrations handle production)
    with app.app_context():
        db.create_all()

    session = GameSession(game=ChessGame())

    # ------------------------------------------------------------------
    # Static
    # ------------------------------------------------------------------

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # ------------------------------------------------------------------
    # State / moves
    # ------------------------------------------------------------------

    @app.get("/api/state")
    def state():
        payload = session.game.state()
        payload["session"] = session.mode_info()
        return jsonify(payload)

    @app.get("/api/moves")
    def moves():
        origin = request.args.get("from", "")
        try:
            return jsonify({
                "ok": True,
                "from": origin.strip().lower(),
                "moves": session.game.legal_moves_for(origin),
                "state": _state_with_session(session),
            })
        except InvalidMoveError as exc:
            return jsonify({
                "ok": False,
                "error": str(exc),
                "moves": [],
                "state": _state_with_session(session),
            }), 400

    @app.post("/api/move")
    def move():
        payload = request.get_json(silent=True) or {}
        origin = payload.get("from", "")
        target = payload.get("to", "")
        promotion = payload.get("promotion")

        # In vs-bot mode we refuse to apply a move on behalf of the bot side.
        if session.mode == MODE_VS_BOT and session.bot_color == session.game.turn:
            return jsonify({
                "ok": False,
                "error": "Este randul botului — foloseste /api/bot_move.",
                "state": _state_with_session(session),
            }), 400

        try:
            next_state = session.game.move(origin, target, promotion=promotion)
            next_state["session"] = session.mode_info()
            return jsonify({
                "ok": True,
                "move": {
                    "from": origin.strip().lower(),
                    "to": target.strip().lower(),
                    "promotion": promotion,
                },
                "state": next_state,
            })
        except InvalidMoveError as exc:
            return jsonify({
                "ok": False,
                "error": str(exc),
                "state": _state_with_session(session),
            }), 400

    # ------------------------------------------------------------------
    # Bot
    # ------------------------------------------------------------------

    @app.post("/api/bot_move")
    def bot_move():
        if session.mode != MODE_VS_BOT or session.engine is None:
            return jsonify({
                "ok": False,
                "error": "Modul curent nu are bot activ.",
                "state": _state_with_session(session),
            }), 400

        if session.bot_color != session.game.turn:
            return jsonify({
                "ok": False,
                "error": "Nu este randul botului.",
                "state": _state_with_session(session),
            }), 400

        # If the game has ended, refuse politely.
        if session.game.state().get("status") != "active":
            return jsonify({
                "ok": False,
                "error": "Partida s-a terminat.",
                "state": _state_with_session(session),
            }), 400

        try:
            origin, target, promotion = session.engine.choose_move(session.game)
            next_state = session.game.move(origin, target, promotion=promotion)
            next_state["session"] = session.mode_info()
            return jsonify({
                "ok": True,
                "move": {"from": origin, "to": target, "promotion": promotion},
                "state": next_state,
            })
        except (InvalidMoveError, RuntimeError) as exc:
            return jsonify({
                "ok": False,
                "error": f"Botul nu a putut muta: {exc}",
                "state": _state_with_session(session),
            }), 500

    # ------------------------------------------------------------------
    # Session control
    # ------------------------------------------------------------------

    @app.post("/api/new_game")
    def new_game():
        """Start a new game with a given mode.

        Request body:
          {
            "mode": "local" | "vs_bot",
            "botColor": "white" | "black"      (only for vs_bot)
          }

        The engine is always MCTS; it is not selectable from the client.
        """
        payload = request.get_json(silent=True) or {}
        mode = (payload.get("mode") or MODE_LOCAL).strip().lower()
        bot_color = payload.get("botColor")

        if mode not in VALID_MODES:
            return jsonify({"ok": False, "error": f"Mod necunoscut: {mode!r}."}), 400

        if mode == MODE_VS_BOT:
            if bot_color not in {"white", "black"}:
                return jsonify({
                    "ok": False,
                    "error": "botColor trebuie sa fie 'white' sau 'black'.",
                }), 400
            session.engine = build_engine("mcts")
        else:
            session.engine = None
            bot_color = None

        session.game.reset()
        session.mode = mode
        session.bot_color = bot_color
        session.engine_name = "mcts"

        return jsonify({"ok": True, "state": _state_with_session(session)})

    @app.post("/api/undo")
    def undo():
        try:
            # In vs-bot mode, undoing JUST the bot's reply would leave the
            # board on the bot's turn — the bot would immediately replay
            # (likely the same move). So we undo two plies, ending with the
            # human to move again. Skip the second undo if there is nothing
            # left to undo (e.g. only the bot's opening move existed).
            session.game.undo()
            if (
                session.mode == MODE_VS_BOT
                and session.bot_color is not None
                and session.game.turn == session.bot_color
                and session.game.history
            ):
                session.game.undo()
            return jsonify({"ok": True, "state": _state_with_session(session)})
        except InvalidMoveError as exc:
            return jsonify({
                "ok": False,
                "error": str(exc),
                "state": _state_with_session(session),
            }), 400

    @app.post("/api/reset")
    def reset():
        """Reset the board, keeping the current mode/bot settings."""
        session.game.reset()
        return jsonify({"ok": True, "state": _state_with_session(session)})

    return app


def _state_with_session(session: GameSession) -> dict:
    payload = session.game.state()
    payload["session"] = session.mode_info()
    return payload


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1").lower() not in {"0", "false", "no"}
    app.run(host=host, port=port, debug=debug)
