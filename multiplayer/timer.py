from __future__ import annotations

import math
import time
from typing import Optional

from chessmate.core import BLACK, WHITE, opponent


class GameClock:
    def __init__(self, base_seconds: int, increment_sec: int) -> None:
        self.remaining = {
            WHITE: float(base_seconds),
            BLACK: float(base_seconds),
        }
        self.increment = float(increment_sec)
        self.active_color = WHITE
        self.last_tick: Optional[float] = None
        self.running = False

    def start(self, color: str) -> None:
        self.active_color = color
        self.last_tick = time.monotonic()
        self.running = True

    def pause(self) -> None:
        if self.running:
            self._apply_elapsed(time.monotonic())
        self.running = False

    def _apply_elapsed(self, now: float) -> None:
        if not self.running:
            self.last_tick = now
            return
        if self.last_tick is None:
            self.last_tick = now
            return
        elapsed = now - self.last_tick
        if elapsed <= 0:
            self.last_tick = now
            return
        self.remaining[self.active_color] = max(
            0.0, self.remaining[self.active_color] - elapsed
        )
        self.last_tick = now

    def tick(self) -> Optional[str]:
        now = time.monotonic()
        self._apply_elapsed(now)
        return self.flagged_color()

    def on_move(self, mover_color: str) -> None:
        now = time.monotonic()
        self._apply_elapsed(now)
        if mover_color == self.active_color:
            self.remaining[mover_color] += self.increment
            self.active_color = opponent(mover_color)
            self.last_tick = now

    def flagged_color(self) -> Optional[str]:
        for color, value in self.remaining.items():
            if value <= 0:
                return color
        return None

    def snapshot_payload(self, *, update: bool = True) -> dict[str, object]:
        if update:
            self._apply_elapsed(time.monotonic())
        return {
            WHITE: int(math.ceil(max(0.0, self.remaining[WHITE]))),
            BLACK: int(math.ceil(max(0.0, self.remaining[BLACK]))),
            "active": self.active_color,
        }
