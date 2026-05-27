"""Puzzle module — loads Lichess CSV puzzles and manages active puzzle sessions."""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from typing import Optional

from .core import ChessGame, InvalidMoveError, WHITE, BLACK, QUEEN, ROOK, BISHOP, KNIGHT

_UCI_PROMO: dict[str, str] = {"q": QUEEN, "r": ROOK, "b": BISHOP, "n": KNIGHT}


def _parse_uci(uci: str) -> tuple[str, str, Optional[str]]:
    """Return (from_sq, to_sq, promotion_kind) from a UCI move string."""
    uci = uci.strip().lower()
    promo = _UCI_PROMO.get(uci[4:5]) if len(uci) > 4 else None
    return uci[:2], uci[2:4], promo


@dataclass
class PuzzleData:
    """Parsed row from the Lichess puzzle CSV."""
    puzzle_id: str
    fen: str
    moves: list[str]   # UCI strings; moves[0] is the setup move
    rating: int
    themes: list[str]
    game_url: str

    @classmethod
    def from_row(cls, row: dict) -> "PuzzleData":
        return cls(
            puzzle_id=row["PuzzleId"],
            fen=row["FEN"],
            moves=row["Moves"].split(),
            rating=int(row["Rating"]),
            themes=row.get("Themes", "").split() if row.get("Themes") else [],
            game_url=row.get("GameUrl", ""),
        )


class PuzzleLoader:
    """Loads puzzles from a Lichess CSV and supports theme-filtered random access."""

    def __init__(self, csv_path: str, max_puzzles: int = 50_000) -> None:
        self.puzzles: list[PuzzleData] = []
        self._by_theme: dict[str, list[int]] = {}
        self._load(csv_path, max_puzzles)
        self._all_themes: list[str] = sorted(self._by_theme.keys())

    _CSV_FIELDS = [
        "PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation",
        "Popularity", "NbPlays", "Themes", "GameUrl", "OpeningTags",
    ]

    def _load(self, csv_path: str, max_puzzles: int) -> None:
        with open(csv_path, newline="", encoding="utf-8") as f:
            first = f.readline()
            # If the file has a header row, keep it consumed; otherwise rewind.
            if not first.startswith("PuzzleId"):
                f.seek(0)
            reader = csv.DictReader(f, fieldnames=self._CSV_FIELDS)
            for row in reader:
                if len(self.puzzles) >= max_puzzles:
                    break
                try:
                    p = PuzzleData.from_row(row)
                except (ValueError, KeyError):
                    continue
                # Need at least setup move + one user move
                if len(p.moves) < 2:
                    continue
                idx = len(self.puzzles)
                self.puzzles.append(p)
                for theme in p.themes:
                    self._by_theme.setdefault(theme, []).append(idx)

    def get_themes(self) -> list[str]:
        return self._all_themes

    def get_random(self, theme: Optional[str] = None) -> Optional[PuzzleData]:
        if theme and theme in self._by_theme:
            indices = self._by_theme[theme]
        elif self.puzzles:
            indices = list(range(len(self.puzzles)))
        else:
            return None
        return self.puzzles[random.choice(indices)]


class PuzzleSession:
    """Manages the state of a single active puzzle.

    Lichess puzzle format:
      - FEN   : position before moves[0]
      - moves[0] : opponent's "setup" move (applied automatically)
      - moves[1], moves[3], ... : user must find these
      - moves[2], moves[4], ... : opponent responses (applied automatically)
    """

    def __init__(self, puzzle: PuzzleData) -> None:
        self.puzzle = puzzle
        self.game = ChessGame()
        self.current_step: int = 0       # index into solution_moves
        self.solver_color: str = ""
        self.solution_moves: list[str] = []
        self._setup()

    def _setup(self) -> None:
        self.game.load_fen(self.puzzle.fen)
        from_sq, to_sq, promo = _parse_uci(self.puzzle.moves[0])
        self.game.move(from_sq, to_sq, promotion=promo)
        self.solver_color = self.game.turn
        self.solution_moves = self.puzzle.moves[1:]
        self.current_step = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def try_move(
        self,
        from_sq: str,
        to_sq: str,
        promotion: Optional[str] = None,
    ) -> dict:
        """Attempt a user move.

        Returns a response dict with:
          ok, correct, complete, state  — on correct move
          ok=False, correct=False, error, state  — on wrong move
          ok=False, error  — on other errors (puzzle already complete)
        """
        if self.is_complete():
            return {"ok": False, "error": "Puzzle-ul este deja rezolvat."}

        exp_from, exp_to, exp_promo = _parse_uci(self.solution_moves[self.current_step])
        actual_from = from_sq.strip().lower()
        actual_to = to_sq.strip().lower()
        actual_promo = promotion.strip().lower() if promotion else None

        if actual_from != exp_from or actual_to != exp_to or actual_promo != exp_promo:
            return {
                "ok": False,
                "correct": False,
                "error": "Mutare greșită. Încearcă din nou.",
                "state": self.get_state(),
            }

        # Correct — apply user's move
        try:
            state = self.game.move(actual_from, actual_to, promotion=actual_promo)
        except InvalidMoveError as exc:
            return {"ok": False, "error": str(exc), "state": self.get_state()}

        self.current_step += 1

        if self.is_complete():
            return {"ok": True, "correct": True, "complete": True, "state": self._decorate(state)}

        # Apply opponent response automatically
        opp_from, opp_to, opp_promo = _parse_uci(self.solution_moves[self.current_step])
        try:
            state = self.game.move(opp_from, opp_to, promotion=opp_promo)
        except InvalidMoveError:
            pass  # Opponent response failed — puzzle data issue; still advance
        self.current_step += 1

        complete = self.is_complete()
        return {
            "ok": True,
            "correct": True,
            "complete": complete,
            "state": self._decorate(state),
        }

    def is_complete(self) -> bool:
        return self.current_step >= len(self.solution_moves)

    def get_state(self) -> dict:
        return self._decorate(self.game.state())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _decorate(self, state: dict) -> dict:
        """Attach puzzle metadata and session info to a game state dict."""
        state["puzzle"] = {
            "id": self.puzzle.puzzle_id,
            "rating": self.puzzle.rating,
            "themes": self.puzzle.themes,
            "solverColor": self.solver_color,
            "totalSteps": len(self.solution_moves),
            "completedSteps": self.current_step,
            "isComplete": self.is_complete(),
            "gameUrl": self.puzzle.game_url,
        }
        state["session"] = {"mode": "puzzle", "solverColor": self.solver_color}
        state["canUndo"] = False
        return state
