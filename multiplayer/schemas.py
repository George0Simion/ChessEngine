from __future__ import annotations

from typing import Optional

from .settings import ALLOWED_TIME_CONTROLS, DEFAULT_TIME_CONTROL

PROMO_TO_UCI = {
    "queen": "q",
    "rook": "r",
    "bishop": "b",
    "knight": "n",
}


def normalize_time_control(minutes: Optional[int]) -> int:
    if minutes in ALLOWED_TIME_CONTROLS:
        return minutes
    return DEFAULT_TIME_CONTROL


def move_to_uci(origin: str, target: str, promotion: Optional[str]) -> str:
    if promotion:
        suffix = PROMO_TO_UCI.get(promotion)
        if suffix:
            return f"{origin}{target}{suffix}"
    return f"{origin}{target}"
