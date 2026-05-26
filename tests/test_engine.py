"""Smoke tests for the engine module.

These are deliberately tiny: the goal is to confirm that the engine
contract is honoured (legal move out, error on dead position, fast-path
state restoration after every search) — NOT to measure playing strength.

MCTS tests use very small `simulations` / `time_budget` values to keep
the suite fast.
"""

import unittest

from chessmate.core import (
    BLACK,
    KING,
    QUEEN,
    WHITE,
    ChessGame,
    Piece,
)
from chessmate.engine import MCTSEngine, build_engine


class MCTSEngineTest(unittest.TestCase):
    def test_returns_legal_move_from_initial_position(self):
        game = ChessGame()
        engine = MCTSEngine(simulations=8, rollout_depth=4, time_budget=2.0, seed=0)

        origin, destination, promotion = engine.choose_move(game)

        legal = set(game.all_legal_moves(game.turn))
        self.assertIn((origin, destination, promotion), legal)

    def test_search_does_not_mutate_game_state(self):
        """MCTS must perfectly undo every move it explored."""
        game = ChessGame()
        before_board = {sq: (p.color, p.kind) for sq, p in game.board.items()}
        before_turn = game.turn
        before_history_len = len(game.history)

        MCTSEngine(simulations=15, rollout_depth=4, time_budget=2.0, seed=1).choose_move(game)

        after_board = {sq: (p.color, p.kind) for sq, p in game.board.items()}
        self.assertEqual(before_board, after_board)
        self.assertEqual(before_turn, game.turn)
        self.assertEqual(before_history_len, len(game.history))

    def test_short_circuits_when_only_one_legal_move(self):
        # Black king in check by white queen on h7 with only one escape: Kxh7.
        # White king tucked far away so it doesn't interfere with the test.
        game = ChessGame()
        game.board = {
            "a1": Piece(WHITE, KING),
            "h8": Piece(BLACK, KING),
            "h7": Piece(WHITE, QUEEN),
        }
        game.turn = BLACK
        game._cached_status = None

        engine = MCTSEngine(simulations=1000, time_budget=2.0, seed=0)
        move = engine.choose_move(game)

        # Only legal response is Kxh7 (king takes queen).
        self.assertEqual(("h8", "h7", None), move)

    def test_raises_when_no_legal_moves_available(self):
        game = ChessGame()
        game.board = {
            "a8": Piece(BLACK, KING),
            "c7": Piece(WHITE, QUEEN),
            "c6": Piece(WHITE, KING),
        }
        game.turn = BLACK
        game._cached_status = None

        with self.assertRaises(RuntimeError):
            MCTSEngine(simulations=4, time_budget=1.0, seed=0).choose_move(game)


class BuildEngineTest(unittest.TestCase):
    def test_builds_mcts_by_name(self):
        engine = build_engine("mcts")
        self.assertIsInstance(engine, MCTSEngine)

    def test_default_is_mcts(self):
        # Empty / blank name should fall through to the only available engine.
        self.assertIsInstance(build_engine(""), MCTSEngine)

    def test_default_with_no_argument_is_mcts(self):
        # No name at all => factory still works.
        self.assertIsInstance(build_engine(), MCTSEngine)

    def test_unknown_engine_name_raises(self):
        with self.assertRaisesRegex(ValueError, "necunoscut"):
            build_engine("alpha-zero")


if __name__ == "__main__":
    unittest.main()
