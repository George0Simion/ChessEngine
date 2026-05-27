"""Transposition table.

We store plain tuples (faster than NamedTuple field access in the hot path):

    entry = (key, depth, flag, score, move, age)
              [0]   [1]    [2]    [3]   [4]   [5]

Replacement strategy: replace iff the slot is empty, the slot is from an
older search, the slot keys match, OR the new entry searches at least as
deep as the existing one.
"""

from __future__ import annotations
from typing import Optional, Tuple

TT_EXACT = 0
TT_LOWER = 1
TT_UPPER = 2

TTEntry = Tuple[int, int, int, int, int, int]


class TranspositionTable:
    def __init__(self, mb: int = 32):
        slots = max(1024, (mb * 1024 * 1024) // 32)
        self.size = slots
        self.table: list = [None] * slots
        self.age = 0
        self.hits = 0
        self.stores = 0

    def new_search(self) -> None:
        self.age = (self.age + 1) & 0xFFFF

    def probe(self, key: int) -> Optional[TTEntry]:
        e = self.table[key % self.size]
        if e is not None and e[0] == key:
            self.hits += 1
            return e
        return None

    def store(self, key: int, depth: int, flag: int, score: int, move: int) -> None:
        idx = key % self.size
        prev = self.table[idx]
        if (prev is None
                or prev[5] != self.age
                or prev[0] == key
                or prev[1] <= depth):
            self.table[idx] = (key, depth, flag, score, move, self.age)
            self.stores += 1

    def clear(self) -> None:
        for i in range(self.size):
            self.table[i] = None
        self.hits = 0
        self.stores = 0
