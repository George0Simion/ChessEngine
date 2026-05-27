from __future__ import annotations

from datetime import datetime

from models import db


class OnlineGame(db.Model):
    __tablename__ = "online_games"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False, unique=True)
    room_id = db.Column(db.String(36), nullable=False, unique=True)
    time_base_min = db.Column(db.Integer, nullable=False, default=3)
    increment_sec = db.Column(db.Integer, nullable=False, default=2)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
