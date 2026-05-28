from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# Load a local .env if present (no-op in production where env vars are set by
# the platform). python-dotenv is a declared dependency.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from flask import Flask, jsonify, request, send_from_directory

from chessmate import ChessGame, InvalidMoveError
from chessmate.puzzle import PuzzleLoader, PuzzleSession
from models import db, User, Rating, Game
from flask_migrate import Migrate
from auth import auth_bp
from backend.games import games_bp
from engine import api as engine_api


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
    engine_name: str = "alphabeta"
    bot_level: int = 3

    def mode_info(self) -> dict:
        return {
            "mode": self.mode,
            "botColor": self.bot_color,
            "engine": self.engine_name if self.mode == MODE_VS_BOT else None,
        }


def create_app() -> Flask:
    # Persistent runtime files (SQLite fallback DB, analysis cache) live under
    # the Flask instance folder. In production set DATA_DIR (e.g. a mounted
    # disk) to relocate them; locally it defaults to <project>/instance.
    data_dir = os.environ.get("DATA_DIR")
    if data_dir:
        app = Flask(
            __name__, static_folder="static", static_url_path="/static",
            instance_path=os.path.abspath(data_dir),
        )
    else:
        app = Flask(__name__, static_folder="static", static_url_path="/static")
    os.makedirs(app.instance_path, exist_ok=True)

    # ------------------------------------------------------------------ Config
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        db_path = os.path.join(app.instance_path, "chessmate.db")
        db_url = f"sqlite:///{db_path.replace(os.sep, '/') }"
    # Heroku/Render use postgres:// but SQLAlchemy 1.4+ needs postgresql://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "dev-secret-change-in-production"
    )
    # JWT signing key: prefer a dedicated secret, fall back to SECRET_KEY so a
    # single configured secret still works.
    app.config["JWT_SECRET_KEY"] = (
        os.environ.get("JWT_SECRET_KEY") or app.config["SECRET_KEY"]
    )

    db.init_app(app)
    Migrate(app, db)
    app.register_blueprint(auth_bp)
    app.register_blueprint(games_bp)

    # Auto-create tables in development (migrations handle production).
    # Also opportunistically ALTER TABLE for new columns that may not exist
    # in an older sqlite file from a previous schema version.
    with app.app_context():
        db.create_all()
        _ensure_games_schema()

    session = GameSession(game=ChessGame(), engine_name="alphabeta")

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

    # ------ Unified play pages (all served by the same polished board) ------
    @app.get("/play")
    @app.get("/play/bot")
    @app.get("/play/local")
    @app.get("/play/online")
    @app.get("/puzzles")
    def play_page():
        return send_from_directory(app.static_folder, "play.html")

    # Login is just the home page (the home knows how to open the modal).
    @app.get("/login")
    def login_alias():
        return send_from_directory(app.static_folder, "index.html")

    # Dedicated profile page.
    @app.get("/profile")
    def profile_page():
        return send_from_directory(app.static_folder, "profile.html")

    # Game review page (auth-gated client-side; the backend endpoints enforce ownership).
    @app.get("/games/<int:game_id>/review")
    def review_page(game_id):
        return send_from_directory(app.static_folder, "review.html")

    # Local (unsaved) game review — moves come from the client via sessionStorage.
    @app.get("/review")
    def review_local_page():
        return send_from_directory(app.static_folder, "review.html")

    # Backwards compat: the old /bot path used to serve a separate page.
    @app.get("/bot")
    def bot_redirect():
        from flask import redirect
        return redirect("/play/bot", code=301)

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
                "error": "Multiplayer uses WebSocket for moves.",
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
                "error": "Multiplayer moves are sent via WebSocket.",
                "state": _state_with_session(session),
            }), 400

        # In vs-bot mode we refuse to apply a move on behalf of the bot side.
        if session.mode == MODE_VS_BOT and session.bot_color == session.game.turn:
            return jsonify({
                "ok": False,
                "error": "It's the bot's turn — use /api/bot_move.",
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
        if session.mode != MODE_VS_BOT:
            return jsonify({
                "ok": False,
                "error": "No bot is active in the current mode.",
                "state": _state_with_session(session),
            }), 400

        if session.bot_color != session.game.turn:
            return jsonify({
                "ok": False,
                "error": "It's not the bot's turn.",
                "state": _state_with_session(session),
            }), 400

        # If the game has ended, refuse politely.
        if session.game.state().get("status") != "active":
            return jsonify({
                "ok": False,
                "error": "The game has ended.",
                "state": _state_with_session(session),
            }), 400

        try:
            fen = session.game.to_fen()
            result = engine_api.best_move(fen, level=session.bot_level)
            uci = result.get("move")
            if not uci:
                raise RuntimeError("Motorul nu a returnat nicio mutare.")
            origin = uci[:2]
            target = uci[2:4]
            promotion = result.get("promotion")
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
                "error": f"The bot could not move: {exc}",
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
        """
        payload = request.get_json(silent=True) or {}
        mode = (payload.get("mode") or MODE_LOCAL).strip().lower()
        bot_color = payload.get("botColor")

        if mode not in VALID_MODES:
            return jsonify({"ok": False, "error": f"Unknown mode: {mode!r}."}), 400

        if mode == MODE_VS_BOT:
            if bot_color not in {"white", "black"}:
                return jsonify({
                    "ok": False,
                    "error": "botColor must be 'white' or 'black'.",
                }), 400
            level_raw = payload.get("level", 3)
            try:
                level = max(1, min(4, int(level_raw)))
            except (TypeError, ValueError):
                level = 3
            session.bot_level = level
        else:
            bot_color = None
            session.bot_level = 3

        session.game.reset()
        session.mode = mode
        session.bot_color = bot_color
        session.engine_name = "alphabeta"

        return jsonify({"ok": True, "state": _state_with_session(session)})

    @app.post("/api/undo")
    def undo():
        if session.mode == MODE_MULTIPLAYER:
            return jsonify({
                "ok": False,
                "error": "Undo is not available in multiplayer.",
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
                "error": "Multiplayer reset is done via WebSocket.",
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
            return jsonify({"ok": False, "error": "No puzzle is active.", "moves": []}), 404
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
            return jsonify({"ok": False, "error": "No puzzle is active."}), 404
        if puzzle_session.is_complete():
            return jsonify({"ok": False, "error": "The puzzle is already solved."}), 400
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
            return jsonify({"ok": False, "error": "No puzzle found."}), 404

        try:
            puzzle_session = PuzzleSession(puzzle_data)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Failed to load puzzle: {exc}"}), 500

        return jsonify({"ok": True, "state": puzzle_session.get_state()})

    @app.get("/api/puzzle/state")
    def puzzle_state_endpoint():
        if puzzle_session is None:
            return jsonify({"ok": False, "error": "No puzzle is active."}), 404
        return jsonify({"ok": True, "state": puzzle_session.get_state()})

    @app.post("/api/puzzle/move")
    def puzzle_move():
        if puzzle_session is None:
            return jsonify({"ok": False, "error": "No puzzle is active."}), 404

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
        "The puzzle database is not available. "
        "Download the CSV file from Kaggle and set "
        "PUZZLE_CSV_PATH to its path."
    )


def _ensure_games_schema() -> None:
    """Add any missing columns to the `games` table (idempotent).

    `db.create_all()` only creates missing TABLES — it won't add missing
    COLUMNS. When the schema evolves we ALTER TABLE here so an older sqlite
    file from a previous build keeps working without manual migrations.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    try:
        existing = {c["name"] for c in inspector.get_columns("games")}
    except Exception:
        return  # table doesn't exist yet, create_all handled it

    dialect = db.engine.dialect.name
    bool_default = "FALSE" if dialect == "postgresql" else "0"
    datetime_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"

    needed = [
        ("white_is_bot",  f"BOOLEAN NOT NULL DEFAULT {bool_default}"),
        ("black_is_bot",  f"BOOLEAN NOT NULL DEFAULT {bool_default}"),
        ("bot_level",     "INTEGER"),
        ("current_fen",   "TEXT"),
        ("result_reason", "VARCHAR(40)"),
        ("updated_at",    datetime_type),
    ]
    fen_start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

    for col, sql_type in needed:
        if col in existing:
            continue
        try:
            db.session.execute(text(f"ALTER TABLE games ADD COLUMN {col} {sql_type}"))
            db.session.commit()
        except Exception:
            db.session.rollback()
            continue

    # Backfill defaults for rows from older schemas.
    try:
        db.session.execute(text(
            "UPDATE games SET current_fen = :fen WHERE current_fen IS NULL"
        ), {"fen": fen_start})
        db.session.execute(text(
            "UPDATE games SET moves_history = '' WHERE moves_history IS NULL"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    # Debug is OFF unless explicitly enabled, so `python app.py` is prod-safe.
    # (Production normally runs via gunicorn, which never executes this block.)
    flask_env = os.environ.get("FLASK_ENV", "").lower()
    debug = (
        os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
        or flask_env == "development"
    )
    app.run(host=host, port=port, debug=debug)
