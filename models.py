from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rating = db.relationship(
        'Rating', backref='user', uselist=False, cascade="all, delete-orphan",
    )


class Rating(db.Model):
    __tablename__ = 'ratings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Glicko-2 starting values per spec.
    rating = db.Column(db.Float, default=1500.0)
    rd = db.Column(db.Float, default=350.0)
    vol = db.Column(db.Float, default=0.06)


class Game(db.Model):
    __tablename__ = 'games'

    id = db.Column(db.Integer, primary_key=True)

    # Null = bot occupies that side.
    white_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    black_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Whether each side is the bot. (Redundant with NULL ids but explicit and
    # safer when we later allow registered bot accounts.)
    white_is_bot = db.Column(db.Boolean, default=False, nullable=False)
    black_is_bot = db.Column(db.Boolean, default=False, nullable=False)
    bot_level = db.Column(db.Integer, nullable=True)   # 1..4 when a bot plays

    # Live position + move log (UCI moves separated by spaces).
    current_fen = db.Column(
        db.Text,
        default="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        nullable=False,
    )
    moves_history = db.Column(db.Text, default="", nullable=False)

    # active | white_win | black_win | draw | aborted
    status = db.Column(db.String(20), default='active', nullable=False)

    # checkmate | stalemate | resignation | draw_50_move |
    # draw_insufficient | draw_threefold | timeout | illegal_move | None
    result_reason = db.Column(db.String(40), nullable=True)

    # Kept for backwards compat with the older endpoint (set together with status).
    winner = db.Column(db.String(10), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
    )
