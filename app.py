from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

from chessmate import ChessGame, InvalidMoveError, build_engine
from chessmate.engine import Engine
from chessmate.puzzle import PuzzleLoader, PuzzleSession
from models import db, User, Rating, Game
from flask_migrate import Migrate
from auth import auth_bp


MODE_LOCAL = "local"      # 1v1 hot-seat
MODE_VS_BOT = "vs_bot"    # human vs engine
MODE_MULTIPLAYER = "multiplayer"  # online matchmaking via WebSocket

VALID_MODES = {MODE_LOCAL, MODE_VS_BOT, MODE_MULTIPLAYER}


PUZZLE_CSV_PATH = os.path.join(os.path.dirname(__file__), "lichess_db_puzzle.csv")


def _find_puzzle_csv() -> Optional[str]:
    return PUZZLE_CSV_PATH if os.path.isfile(PUZZLE_CSV_PATH) else None


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
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "chessmate.db"))
        db_url = f"sqlite:///{db_path.replace(os.sep, '/') }"
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

    # Puzzle state — lazy-loaded on first puzzle request.
    puzzle_loader: Optional[PuzzleLoader] = None
    puzzle_session: Optional[PuzzleSession] = None

    def _get_loader() -> Optional[PuzzleLoader]:
        nonlocal puzzle_loader
        if puzzle_loader is None:
            csv_path = _find_puzzle_csv()
            if csv_path is None:
                return None
            puzzle_loader = PuzzleLoader(csv_path)
        return puzzle_loader

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

    @app.get("/api/mp_config")
    def mp_config():
        mp_ws_url = os.environ.get("MP_WS_URL")
        if mp_ws_url:
            return jsonify({
                "ok": True,
                "wsUrl": mp_ws_url,
                "baseMinutes": [3, 5, 10],
                "incrementSec": 2,
            })

        host = os.environ.get("MP_HOST")
        if not host:
            host = request.host.split(":")[0]
        mp_port = int(os.environ.get("MP_PORT", "8000"))
        scheme = "wss" if request.scheme == "https" else "ws"
        ws_url = f"{scheme}://{host}:{mp_port}/ws"
        return jsonify({
            "ok": True,
            "wsUrl": ws_url,
            "baseMinutes": [3, 5, 10],
            "incrementSec": 2,
        })

    @app.get("/api/moves")
    def moves():
        if session.mode == MODE_MULTIPLAYER:
            return jsonify({
                "ok": False,
                "error": "Multiplayer foloseste WebSocket pentru mutari.",
                "moves": [],
                "state": _state_with_session(session),
            }), 400
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

        if session.mode == MODE_MULTIPLAYER:
            return jsonify({
                "ok": False,
                "error": "Mutarile multiplayer se trimit prin WebSocket.",
                "state": _state_with_session(session),
            }), 400

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
        elif mode == MODE_MULTIPLAYER:
            session.engine = None
            bot_color = None
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
        if session.mode == MODE_MULTIPLAYER:
            return jsonify({
                "ok": False,
                "error": "Undo nu este disponibil in multiplayer.",
                "state": _state_with_session(session),
            }), 400
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
        if session.mode == MODE_MULTIPLAYER:
            return jsonify({
                "ok": False,
                "error": "Resetul multiplayer se face prin WebSocket.",
                "state": _state_with_session(session),
            }), 400
        """Reset the board, keeping the current mode/bot settings."""
        session.game.reset()
        return jsonify({"ok": True, "state": _state_with_session(session)})

    # ------------------------------------------------------------------
    # Puzzle
    # ------------------------------------------------------------------

    @app.get("/api/puzzle/moves")
    def puzzle_moves():
        if puzzle_session is None:
            return jsonify({"ok": False, "error": "Niciun puzzle activ.", "moves": []}), 404
        origin = request.args.get("from", "")
        try:
            return jsonify({
                "ok": True,
                "from": origin.strip().lower(),
                "moves": puzzle_session.game.legal_moves_for(origin),
                "state": puzzle_session.get_state(),
            })
        except InvalidMoveError as exc:
            return jsonify({
                "ok": False,
                "error": str(exc),
                "moves": [],
                "state": puzzle_session.get_state(),
            }), 400

    @app.get("/api/puzzle/hint")
    def puzzle_hint():
        if puzzle_session is None:
            return jsonify({"ok": False, "error": "Niciun puzzle activ."}), 404
        if puzzle_session.is_complete():
            return jsonify({"ok": False, "error": "Puzzle-ul este deja rezolvat."}), 400
        uci = puzzle_session.solution_moves[puzzle_session.current_step]
        return jsonify({
            "ok": True,
            "from": uci[:2],
            "to": uci[2:4],
        })

    @app.get("/api/puzzle/themes")
    def puzzle_themes():
        loader = _get_loader()
        if loader is None:
            return jsonify({"ok": False, "error": _puzzle_unavailable_msg()}), 503
        return jsonify({"ok": True, "themes": loader.get_themes()})

    @app.post("/api/puzzle/new")
    def puzzle_new():
        nonlocal puzzle_session
        loader = _get_loader()
        if loader is None:
            return jsonify({"ok": False, "error": _puzzle_unavailable_msg()}), 503

        body = request.get_json(silent=True) or {}
        theme = (body.get("theme") or "").strip() or None

        puzzle_data = loader.get_random(theme)
        if puzzle_data is None:
            return jsonify({"ok": False, "error": "Nu s-a găsit niciun puzzle."}), 404

        try:
            puzzle_session = PuzzleSession(puzzle_data)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Eroare la încărcarea puzzle-ului: {exc}"}), 500

        return jsonify({"ok": True, "state": puzzle_session.get_state()})

    @app.get("/api/puzzle/state")
    def puzzle_state_endpoint():
        if puzzle_session is None:
            return jsonify({"ok": False, "error": "Niciun puzzle activ."}), 404
        return jsonify({"ok": True, "state": puzzle_session.get_state()})

    @app.post("/api/puzzle/move")
    def puzzle_move():
        if puzzle_session is None:
            return jsonify({"ok": False, "error": "Niciun puzzle activ."}), 404

        body = request.get_json(silent=True) or {}
        from_sq = body.get("from", "")
        to_sq = body.get("to", "")
        promotion = body.get("promotion")

        result = puzzle_session.try_move(from_sq, to_sq, promotion=promotion)
        status_code = 200 if result.get("ok") else 400
        return jsonify(result), status_code

    return app


def _state_with_session(session: GameSession) -> dict:
    payload = session.game.state()
    payload["session"] = session.mode_info()
    return payload


def _puzzle_unavailable_msg() -> str:
    return (
        "Baza de date de puzzle-uri nu este disponibilă. "
        "Descarcă fișierul CSV de pe Kaggle și setează "
        "variabila de mediu PUZZLE_CSV_PATH cu calea către el."
    )


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "1").lower() not in {"0", "false", "no"}
    app.run(host=host, port=port, debug=debug)
