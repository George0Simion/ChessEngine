from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import db


def _normalize_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        db_path = os.path.join(root, "chessmate.db")
        url = f"sqlite:///{db_path.replace(os.sep, '/') }"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


engine = create_engine(_normalize_db_url(), future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    import multiplayer.models  # noqa: F401

    db.Model.metadata.create_all(engine)
