"""Time management for iterative deepening.

We separate the budget into:
  - soft limit: don't START a new ID iteration past this
  - hard limit: ABORT mid-search past this

Both are derived from `max_ms`. The soft limit lets us amortize iterations
gracefully; the hard limit keeps us inside the contract.
"""

from __future__ import annotations
import time
from typing import Optional


class TimeManager:
    def __init__(self, max_ms: int, max_depth: Optional[int] = None,
                 soft_fraction: float = 0.55):
        self.max_ms = max(1, int(max_ms))
        self.max_depth = max_depth
        self.start = time.monotonic()
        self.soft_ms = max(1, int(self.max_ms * soft_fraction))
        self._stop = False

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.start) * 1000)

    def should_stop(self) -> bool:
        """Hard stop — never overshoot by more than a tiny margin."""
        if self._stop:
            return True
        if self.elapsed_ms() >= self.max_ms:
            self._stop = True
            return True
        return False

    def stop(self) -> None:
        self._stop = True

    def should_start_iteration(self, next_depth: int) -> bool:
        """Decide whether to begin another ID iteration."""
        if self.max_depth is not None and next_depth > self.max_depth:
            return False
        return self.elapsed_ms() < self.soft_ms
