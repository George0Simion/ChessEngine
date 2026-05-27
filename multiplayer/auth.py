from __future__ import annotations

from typing import Optional

import jwt

from models import User
from .db import SessionLocal
from .settings import SECRET_KEY


def authenticate_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None

    user_id = payload.get("user_id")
    if not user_id:
        return None

    with SessionLocal() as session:
        user = session.get(User, user_id)
        if not user:
            return None
        rating = user.rating.rating if user.rating else None
        return {
            "id": user.id,
            "username": user.username,
            "rating": round(rating) if rating is not None else None,
        }
