"""ChessMate engine module.

Provides :class:`MCTSEngine` — a Monte Carlo Tree Search baseline with
random rollouts and a depth-capped material+tanh evaluation. Deliberately
*minimal*: the goal is a working scaffold that picks reasonable moves,
not a strong engine. It is structured so that future iterations can
swap in:

  - a smarter evaluator (PSTs, mobility, king safety, …)
  - move-ordering heuristics for the rollout policy
  - transposition tables, etc.

Engines DO NOT own game state; they read it from the ``ChessGame`` passed
to ``choose_move``. They use the fast-path :meth:`ChessGame.engine_make_move`
/ :meth:`ChessGame.engine_undo` to explore the move tree without paying for
SAN building or end-of-turn status scans.
"""

from __future__ import annotations

import math
import random
import time
from typing import Optional

from .core import (
    BLACK,
    PIECE_VALUES,
    WHITE,
    ChessGame,
    opponent,
)


Move = tuple[str, str, Optional[str]]


class Engine:
    """Abstract engine interface.

    Subclasses override :meth:`choose_move` and return a triple
    ``(origin, destination, promotion)``. ``promotion`` is ``None`` for
    moves that do not promote a pawn.
    """

    name = "engine"

    def choose_move(self, game: ChessGame) -> Move:  # pragma: no cover - abstract
        raise NotImplementedError


# ----------------------------------------------------------------------
# MCTS
# ----------------------------------------------------------------------


class _Node:
    """A single node in the MCTS tree.

    ``value_sum`` is accumulated from the perspective of the player who
    chose ``move`` (i.e. ``prior_player``). Visits count is incremented
    every time the node is on a backpropagated path.
    """

    __slots__ = (
        "parent",
        "move",
        "prior_player",
        "to_move",
        "children",
        "untried",
        "value_sum",
        "visits",
    )

    def __init__(
        self,
        parent: Optional["_Node"],
        move: Optional[Move],
        prior_player: str,
        to_move: str,
        untried: list[Move],
    ) -> None:
        self.parent = parent
        self.move = move
        self.prior_player = prior_player
        self.to_move = to_move
        self.children: list["_Node"] = []
        self.untried = untried
        self.value_sum = 0.0
        self.visits = 0


class MCTSEngine(Engine):
    """Monte Carlo Tree Search baseline.

    Configurable knobs:

    * ``simulations`` — maximum number of MCTS iterations to run per move.
      Acts as an upper bound; ``time_budget`` may cut a search short.
    * ``rollout_depth`` — plies to play out in each random simulation
      before falling back to material evaluation.
    * ``time_budget`` — wall-clock seconds; the search stops whichever
      limit is hit first (sims or time).
    * ``exploration`` — UCT exploration constant.
    * ``seed`` — optional RNG seed for reproducibility (tests).

    The defaults are intentionally conservative: this is a baseline that
    should respond in ~1 second on a typical position, not a strong
    opponent.
    """

    name = "mcts"

    def __init__(
        self,
        simulations: int = 120,
        rollout_depth: int = 10,
        time_budget: float = 1.5,
        exploration: float = 1.4,
        seed: Optional[int] = None,
    ) -> None:
        self.simulations = simulations
        self.rollout_depth = rollout_depth
        self.time_budget = time_budget
        self.exploration = exploration
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def choose_move(self, game: ChessGame) -> Move:
        legal = game.all_legal_moves(game.turn)
        if not legal:
            raise RuntimeError("Nicio mutare legala disponibila.")
        if len(legal) == 1:
            return legal[0]

        root = _Node(
            parent=None,
            move=None,
            prior_player=opponent(game.turn),
            to_move=game.turn,
            untried=list(legal),
        )

        start = time.monotonic()
        done = 0
        while done < self.simulations:
            if (time.monotonic() - start) >= self.time_budget:
                break
            self._simulate_once(game, root)
            done += 1

        # Robust pick: most-visited child of the root. Fall back to a
        # random legal move if we somehow never expanded a child (edge
        # case when simulations=0 or time_budget=0).
        if not root.children:
            return self._rng.choice(legal)
        best = max(root.children, key=lambda c: c.visits)
        return best.move  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Single iteration
    # ------------------------------------------------------------------

    def _simulate_once(self, game: ChessGame, root: _Node) -> None:
        path: list[_Node] = [root]
        node = root
        moves_in_tree = 0

        # ---- Selection ----
        while not node.untried and node.children:
            node = self._best_uct_child(node)
            game.engine_make_move(*node.move)  # type: ignore[arg-type]
            moves_in_tree += 1
            path.append(node)

        # ---- Expansion ----
        if node.untried:
            move = node.untried.pop(self._rng.randrange(len(node.untried)))
            game.engine_make_move(*move)
            moves_in_tree += 1
            child_to_move = game.turn
            child = _Node(
                parent=node,
                move=move,
                prior_player=opponent(child_to_move),
                to_move=child_to_move,
                untried=game.all_legal_moves(child_to_move),
            )
            node.children.append(child)
            node = child
            path.append(node)

        # ---- Rollout ----
        rollout_moves = 0
        eval_white = None  # value in [-1, 1] from WHITE's perspective

        current_moves = game.all_legal_moves(game.turn)
        if not current_moves:
            eval_white = self._terminal_value(game)
        else:
            for _ in range(self.rollout_depth):
                mv = self._rng.choice(current_moves)
                game.engine_make_move(*mv)
                rollout_moves += 1
                current_moves = game.all_legal_moves(game.turn)
                if not current_moves:
                    eval_white = self._terminal_value(game)
                    break
            if eval_white is None:
                eval_white = self._material_eval(game, WHITE)

        # ---- Backpropagation ----
        for n in path:
            # ``value_sum`` is from the perspective of n.prior_player. We
            # have eval from WHITE's perspective, so flip when needed.
            if n.prior_player == WHITE:
                n.value_sum += eval_white
            else:
                n.value_sum -= eval_white
            n.visits += 1

        # ---- Undo everything (rollout first, then in-tree moves) ----
        for _ in range(rollout_moves):
            game.engine_undo()
        for _ in range(moves_in_tree):
            game.engine_undo()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _best_uct_child(self, node: _Node) -> _Node:
        log_parent = math.log(max(1, node.visits))
        best: Optional[_Node] = None
        best_score = -float("inf")
        for child in node.children:
            if child.visits == 0:
                return child  # untried via UCT means infinite priority
            mean = child.value_sum / child.visits
            ucb = mean + self.exploration * math.sqrt(log_parent / child.visits)
            if ucb > best_score:
                best_score = ucb
                best = child
        assert best is not None  # node.children non-empty by caller's check
        return best

    @staticmethod
    def _terminal_value(game: ChessGame) -> float:
        """Value of a leaf where the side to move has no legal moves.

        Returns +1.0 if the side-to-move is mated and that result favours
        White, -1.0 if it favours Black, and 0.0 for stalemate. Always
        from White's perspective.
        """
        if game.is_in_check(game.turn):
            # side-to-move is mated -> opponent wins
            return -1.0 if game.turn == WHITE else 1.0
        return 0.0

    @staticmethod
    def _material_eval(game: ChessGame, perspective: str) -> float:
        """Tanh-squashed material balance from ``perspective``'s viewpoint."""
        total = 0
        for piece in game.board.values():
            value = PIECE_VALUES[piece.kind]
            if piece.color == perspective:
                total += value
            else:
                total -= value
        # Squash to [-1, 1]; a ~5-point lead reads as a near-decisive edge.
        return math.tanh(total / 5.0)


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------


def build_engine(name: str = "mcts", **kwargs) -> Engine:
    """Construct an engine by name. Only MCTS is supported currently.

    The factory is kept (rather than inlining ``MCTSEngine(...)`` at call
    sites) so that future iterations can add new engines without touching
    callers — just register them here.
    """
    key = (name or "").strip().lower()
    if key in {"mcts", "tree", "search", ""}:
        return MCTSEngine(**kwargs)
    raise ValueError(f"Engine necunoscut: {name!r}")
