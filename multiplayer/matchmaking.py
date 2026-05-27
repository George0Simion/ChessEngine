from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class QueueEntry:
    user: dict[str, Any]
    websocket: Any
    queued_at: float = field(default_factory=time.monotonic)


class Matchmaker:
    def __init__(self, allowed_minutes: set[int]) -> None:
        self._queues = {minutes: deque() for minutes in allowed_minutes}
        self._user_index: dict[int, int] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self, entry: QueueEntry, minutes: int
    ) -> Optional[tuple[QueueEntry, QueueEntry]]:
        async with self._lock:
            if entry.user["id"] in self._user_index:
                return None
            queue = self._queues.get(minutes)
            if queue is None:
                return None
            if queue:
                other = queue.popleft()
                self._user_index.pop(other.user["id"], None)
                return other, entry
            queue.append(entry)
            self._user_index[entry.user["id"]] = minutes
            return None

    async def remove(self, user_id: int) -> bool:
        async with self._lock:
            minutes = self._user_index.pop(user_id, None)
            if minutes is None:
                return False
            queue = self._queues.get(minutes)
            if queue is None:
                return False
            for idx, entry in enumerate(queue):
                if entry.user["id"] == user_id:
                    del queue[idx]
                    return True
            return True

    async def is_queued(self, user_id: int) -> bool:
        async with self._lock:
            return user_id in self._user_index
