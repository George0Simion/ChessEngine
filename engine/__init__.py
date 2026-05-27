"""ChessMate in-house engine (original implementation).

Public surface:
    Position  - mutable board state
    parse_fen / Position.from_fen
    best_move / analyze_position  (engine.api)
"""

from .board import Position
from .api import best_move, analyze_position

__all__ = ["Position", "best_move", "analyze_position"]
