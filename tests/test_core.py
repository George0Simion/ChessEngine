import unittest

from chessmate.core import (
    BISHOP,
    BLACK,
    KING,
    KNIGHT,
    PAWN,
    QUEEN,
    ROOK,
    WHITE,
    ChessGame,
    InvalidMoveError,
    Piece,
)


class ChessCoreTest(unittest.TestCase):
    def setUp(self):
        self.game = ChessGame()

    # ------------------------------------------------------------------
    # Sprint 1 behaviours
    # ------------------------------------------------------------------

    def test_initial_position_has_standard_pieces_and_white_to_move(self):
        state = self.game.state()

        self.assertEqual(WHITE, state["turn"])
        self.assertEqual(32, len(state["board"]))
        self.assertEqual({"color": WHITE, "kind": KING, "label": "rege", "symbol": "\u2654"}, state["board"]["e1"])
        self.assertEqual({"color": BLACK, "kind": KING, "label": "rege", "symbol": "\u265A"}, state["board"]["e8"])

    def test_white_pawn_can_move_one_or_two_squares_from_start(self):
        self.assertEqual({"e3", "e4"}, set(self.game.legal_moves_for("e2")))

    def test_pawn_is_blocked_by_piece_in_front(self):
        self.game.board["e3"] = Piece(WHITE, KNIGHT)

        self.assertEqual([], self.game.legal_moves_for("e2"))

    def test_pawn_can_capture_diagonally(self):
        self.game.board = {
            "a1": Piece(WHITE, KING),
            "a8": Piece(BLACK, KING),
            "e2": Piece(WHITE, PAWN),
            "d3": Piece(BLACK, KNIGHT),
            "f3": Piece(BLACK, BISHOP),
        }
        self.game.turn = WHITE

        self.assertEqual({"d3", "e3", "e4", "f3"}, set(self.game.legal_moves_for("e2")))

    def test_knight_can_jump_over_occupied_squares(self):
        self.assertEqual({"a3", "c3"}, set(self.game.legal_moves_for("b1")))

    def test_rook_respects_blockers_and_captures(self):
        self.game.board = {
            "a1": Piece(WHITE, KING),
            "a8": Piece(BLACK, KING),
            "d4": Piece(WHITE, ROOK),
            "d6": Piece(WHITE, PAWN),
            "b4": Piece(BLACK, KNIGHT),
        }
        self.game.turn = WHITE

        self.assertEqual(
            {"b4", "c4", "d1", "d2", "d3", "d5", "e4", "f4", "g4", "h4"},
            set(self.game.legal_moves_for("d4")),
        )

    def test_bishop_respects_diagonal_blockers_and_captures(self):
        self.game.board = {
            "a1": Piece(WHITE, KING),
            "h8": Piece(BLACK, KING),
            "d4": Piece(WHITE, BISHOP),
            "f6": Piece(WHITE, PAWN),
            "b2": Piece(BLACK, KNIGHT),
        }
        self.game.turn = WHITE

        self.assertEqual(
            {"a7", "b2", "b6", "c3", "c5", "e3", "e5", "f2", "g1"},
            set(self.game.legal_moves_for("d4")),
        )

    def test_queen_combines_rook_and_bishop_movement(self):
        self.game.board = {
            "a1": Piece(WHITE, KING),
            "h8": Piece(BLACK, KING),
            "d4": Piece(WHITE, QUEEN),
            "d6": Piece(WHITE, PAWN),
            "g7": Piece(BLACK, KNIGHT),
        }
        self.game.turn = WHITE

        moves = set(self.game.legal_moves_for("d4"))

        self.assertIn("d5", moves)
        self.assertNotIn("d6", moves)
        self.assertNotIn("d7", moves)
        self.assertIn("g7", moves)
        self.assertIn("h4", moves)
        self.assertNotIn("a1", moves)

    def test_king_moves_one_square_without_castling(self):
        self.game.board = {
            "a8": Piece(BLACK, KING),
            "e4": Piece(WHITE, KING),
            "e5": Piece(WHITE, PAWN),
            "f5": Piece(BLACK, PAWN),
        }
        self.game.turn = WHITE

        self.assertEqual({"d3", "d4", "d5", "e3", "f3", "f4", "f5"}, set(self.game.legal_moves_for("e4")))

    def test_cannot_select_opponent_piece_on_wrong_turn(self):
        with self.assertRaisesRegex(InvalidMoveError, "Este randul"):
            self.game.legal_moves_for("e7")

    def test_move_updates_board_and_alternates_turn(self):
        state = self.game.move("e2", "e4")

        self.assertNotIn("e2", state["board"])
        self.assertEqual(PAWN, state["board"]["e4"]["kind"])
        self.assertEqual(BLACK, state["turn"])

    def test_cannot_capture_own_piece(self):
        with self.assertRaisesRegex(InvalidMoveError, "propria piesa"):
            self.game.move("e1", "e2")

    def test_invalid_square_is_rejected(self):
        with self.assertRaisesRegex(InvalidMoveError, "Coordonata invalida"):
            self.game.legal_moves_for("i9")

    # ------------------------------------------------------------------
    # History & SAN
    # ------------------------------------------------------------------

    def test_history_records_moves_with_san(self):
        self.game.move("e2", "e4")
        self.game.move("e7", "e5")
        self.game.move("g1", "f3")

        history = self.game.state()["history"]
        self.assertEqual(["e4", "e5", "Nf3"], [entry["san"] for entry in history])
        self.assertEqual([WHITE, BLACK, WHITE], [entry["color"] for entry in history])
        self.assertEqual([1, 1, 2], [entry["number"] for entry in history])

    def test_san_marks_capture_with_x(self):
        self.game.move("e2", "e4")
        self.game.move("d7", "d5")
        self.game.move("e4", "d5")

        self.assertEqual("exd5", self.game.state()["history"][-1]["san"])

    def test_san_marks_check_and_checkmate(self):
        # Fool's mate: 1.f3 e5 2.g4 Qh4#
        self.game.move("f2", "f3")
        self.game.move("e7", "e5")
        self.game.move("g2", "g4")
        self.game.move("d8", "h4")

        history = self.game.state()["history"]
        self.assertEqual("Qh4#", history[-1]["san"])
        self.assertTrue(history[-1]["isCheckmate"])
        self.assertEqual("checkmate", self.game.state()["status"])
        self.assertEqual(BLACK, self.game.state()["winner"])

    # ------------------------------------------------------------------
    # Check / mate / stalemate
    # ------------------------------------------------------------------

    def test_in_check_detected_after_attacking_king(self):
        self.game.board = {
            "a1": Piece(WHITE, KING),
            "h8": Piece(BLACK, KING),
            "h1": Piece(WHITE, QUEEN),
        }
        self.game.turn = WHITE
        state = self.game.move("h1", "h5")
        self.assertTrue(state["inCheck"])
        self.assertEqual("h8", state["checkSquare"])
        self.assertEqual("Qh5+", state["history"][-1]["san"])

    def test_must_respond_to_check(self):
        self.game.board = {
            "e1": Piece(WHITE, KING),
            "e7": Piece(WHITE, ROOK),
            "e8": Piece(BLACK, KING),
        }
        self.game.turn = BLACK

        state = self.game.state()
        self.assertTrue(state["inCheck"])
        self.assertEqual({"d8", "e7", "f8"}, set(self.game.legal_moves_for("e8")))

    def test_stalemate_detected(self):
        self.game.board = {
            "a8": Piece(BLACK, KING),
            "c7": Piece(WHITE, QUEEN),
            "c6": Piece(WHITE, KING),
        }
        self.game.turn = BLACK

        state = self.game.state()
        self.assertEqual("stalemate", state["status"])
        self.assertIsNone(state["winner"])
        self.assertFalse(state["inCheck"])

    def test_cannot_make_move_that_leaves_own_king_in_check(self):
        self.game.board = {
            "e1": Piece(WHITE, KING),
            "e2": Piece(WHITE, BISHOP),
            "e8": Piece(BLACK, ROOK),
            "a8": Piece(BLACK, KING),
        }
        self.game.turn = WHITE

        with self.assertRaisesRegex(InvalidMoveError, "regele"):
            self.game.move("e2", "d3")

    # ------------------------------------------------------------------
    # Castling
    # ------------------------------------------------------------------

    def test_kingside_castling(self):
        self.game.board = {
            "e1": Piece(WHITE, KING),
            "h1": Piece(WHITE, ROOK),
            "e8": Piece(BLACK, KING),
        }
        self.game.turn = WHITE

        state = self.game.move("e1", "g1")

        self.assertEqual({"color": WHITE, "kind": KING, "label": "rege", "symbol": "\u2654"}, state["board"]["g1"])
        self.assertEqual({"color": WHITE, "kind": ROOK, "label": "turn", "symbol": "\u2656"}, state["board"]["f1"])
        self.assertNotIn("e1", state["board"])
        self.assertNotIn("h1", state["board"])
        self.assertEqual("O-O", state["history"][-1]["san"])
        self.assertEqual("K", state["history"][-1]["castling"])

    def test_queenside_castling(self):
        self.game.board = {
            "e1": Piece(WHITE, KING),
            "a1": Piece(WHITE, ROOK),
            "e8": Piece(BLACK, KING),
        }
        self.game.turn = WHITE

        state = self.game.move("e1", "c1")

        self.assertEqual(KING, state["board"]["c1"]["kind"])
        self.assertEqual(ROOK, state["board"]["d1"]["kind"])
        self.assertEqual("O-O-O", state["history"][-1]["san"])

    def test_castling_blocked_when_squares_attacked(self):
        self.game.board = {
            "e1": Piece(WHITE, KING),
            "h1": Piece(WHITE, ROOK),
            "f8": Piece(BLACK, ROOK),
            "a8": Piece(BLACK, KING),
        }
        self.game.turn = WHITE

        self.assertNotIn("g1", self.game.legal_moves_for("e1"))

    def test_castling_lost_after_king_moves(self):
        self.game.board = {
            "e1": Piece(WHITE, KING),
            "h1": Piece(WHITE, ROOK),
            "e8": Piece(BLACK, KING),
        }
        self.game.turn = WHITE

        self.game.move("e1", "e2")
        self.game.move("e8", "d8")
        self.game.move("e2", "e1")
        self.game.move("d8", "e8")

        self.assertNotIn("g1", self.game.legal_moves_for("e1"))

    # ------------------------------------------------------------------
    # En passant
    # ------------------------------------------------------------------

    def test_en_passant_capture(self):
        self.game.board = {
            "a1": Piece(WHITE, KING),
            "a8": Piece(BLACK, KING),
            "e5": Piece(WHITE, PAWN),
            "d7": Piece(BLACK, PAWN),
        }
        self.game.turn = BLACK
        self.game.move("d7", "d5")  # creates en passant target on d6

        self.assertEqual("d6", self.game.en_passant_target)

        state = self.game.move("e5", "d6")

        self.assertEqual({"color": WHITE, "kind": PAWN, "label": "pion", "symbol": "\u2659"}, state["board"]["d6"])
        self.assertNotIn("d5", state["board"])
        self.assertEqual("exd6", state["history"][-1]["san"])

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    def test_pawn_promotes_to_queen_by_default(self):
        self.game.board = {
            "a1": Piece(WHITE, KING),
            "a8": Piece(BLACK, KING),
            "h7": Piece(WHITE, PAWN),
        }
        self.game.turn = WHITE

        state = self.game.move("h7", "h8")

        self.assertEqual(QUEEN, state["board"]["h8"]["kind"])
        self.assertEqual("h8=Q+", state["history"][-1]["san"])

    def test_pawn_can_promote_to_other_piece(self):
        self.game.board = {
            "a1": Piece(WHITE, KING),
            "a8": Piece(BLACK, KING),
            "h7": Piece(WHITE, PAWN),
        }
        self.game.turn = WHITE

        state = self.game.move("h7", "h8", promotion="knight")

        self.assertEqual(KNIGHT, state["board"]["h8"]["kind"])
        self.assertEqual("h8=N", state["history"][-1]["san"])

    def test_promotion_with_invalid_piece_is_rejected(self):
        self.game.board = {
            "a1": Piece(WHITE, KING),
            "a8": Piece(BLACK, KING),
            "h7": Piece(WHITE, PAWN),
        }
        self.game.turn = WHITE

        with self.assertRaisesRegex(InvalidMoveError, "promovare"):
            self.game.move("h7", "h8", promotion="king")

    # ------------------------------------------------------------------
    # Undo
    # ------------------------------------------------------------------

    def test_undo_reverts_last_move(self):
        self.game.move("e2", "e4")
        self.game.undo()

        state = self.game.state()
        self.assertEqual(WHITE, state["turn"])
        self.assertIn("e2", state["board"])
        self.assertNotIn("e4", state["board"])
        self.assertEqual([], state["history"])

    def test_undo_restores_captured_piece(self):
        self.game.move("e2", "e4")
        self.game.move("d7", "d5")
        self.game.move("e4", "d5")
        self.assertEqual([PAWN], self.game.captured[BLACK])

        self.game.undo()

        state = self.game.state()
        self.assertEqual({"color": BLACK, "kind": PAWN, "label": "pion", "symbol": "\u265F"}, state["board"]["d5"])
        self.assertEqual({"color": WHITE, "kind": PAWN, "label": "pion", "symbol": "\u2659"}, state["board"]["e4"])
        self.assertEqual([], self.game.captured[BLACK])

    def test_undo_reverses_castling(self):
        self.game.board = {
            "e1": Piece(WHITE, KING),
            "h1": Piece(WHITE, ROOK),
            "e8": Piece(BLACK, KING),
        }
        self.game.turn = WHITE

        self.game.move("e1", "g1")
        self.game.undo()

        state = self.game.state()
        self.assertIn("e1", state["board"])
        self.assertIn("h1", state["board"])
        self.assertNotIn("f1", state["board"])
        self.assertNotIn("g1", state["board"])
        self.assertTrue(self.game.castling_rights[WHITE]["K"])

    def test_undo_with_no_history_raises(self):
        with self.assertRaisesRegex(InvalidMoveError, "Nu exista"):
            self.game.undo()

    # ------------------------------------------------------------------
    # Captured pieces
    # ------------------------------------------------------------------

    def test_captured_pieces_are_tracked_per_color(self):
        self.game.move("e2", "e4")
        self.game.move("d7", "d5")
        self.game.move("e4", "d5")

        captured = self.game.state()["captured"]
        self.assertEqual([PAWN], captured[BLACK])
        self.assertEqual([], captured[WHITE])


# ----------------------------------------------------------------------
# Sprint 3 additions
# ----------------------------------------------------------------------


class AllLegalMovesTest(unittest.TestCase):
    """``all_legal_moves`` underpins the engine — must enumerate correctly."""

    def setUp(self):
        self.game = ChessGame()

    def test_initial_position_has_20_legal_moves_for_white(self):
        moves = self.game.all_legal_moves(WHITE)
        # 16 pawn moves (8 single + 8 double) + 4 knight moves = 20.
        self.assertEqual(20, len(moves))
        for origin, destination, promotion in moves:
            self.assertIsNone(promotion)

    def test_default_color_is_side_to_move(self):
        moves_default = self.game.all_legal_moves()
        moves_white = self.game.all_legal_moves(WHITE)
        self.assertEqual(set(moves_default), set(moves_white))

    def test_promotion_generates_four_entries(self):
        # Single white pawn one square from promoting; isolated kings elsewhere.
        self.game.board = {
            "a1": Piece(WHITE, KING),
            "a8": Piece(BLACK, KING),
            "h7": Piece(WHITE, PAWN),
        }
        self.game.turn = WHITE

        moves = [m for m in self.game.all_legal_moves(WHITE) if m[0] == "h7"]
        # h7 -> h8 should appear once per promotion piece (Q, R, B, N).
        promotions = sorted(m[2] for m in moves if m[1] == "h8")
        self.assertEqual([BISHOP, KNIGHT, QUEEN, ROOK], promotions)


class InsufficientMaterialTest(unittest.TestCase):
    def setUp(self):
        self.game = ChessGame()

    def _setup(self, board, turn=WHITE):
        self.game.board = board
        self.game.turn = turn
        self.game._cached_status = None

    def test_king_vs_king_is_draw(self):
        self._setup({"a1": Piece(WHITE, KING), "h8": Piece(BLACK, KING)})

        self.assertEqual("draw_insufficient", self.game.state()["status"])

    def test_king_and_bishop_vs_king_is_draw(self):
        self._setup({
            "a1": Piece(WHITE, KING),
            "c1": Piece(WHITE, BISHOP),
            "h8": Piece(BLACK, KING),
        })

        self.assertEqual("draw_insufficient", self.game.state()["status"])

    def test_king_and_knight_vs_king_is_draw(self):
        self._setup({
            "a1": Piece(WHITE, KING),
            "b1": Piece(WHITE, KNIGHT),
            "h8": Piece(BLACK, KING),
        })

        self.assertEqual("draw_insufficient", self.game.state()["status"])

    def test_bishops_same_color_squares_is_draw(self):
        # Both bishops sit on light squares (a-file rank-1 is dark — careful).
        # c1 (file c=2, rank 1=0) -> (2+0)%2 = 0 -> dark square.
        # f4 (file f=5, rank 4=3) -> (5+3)%2 = 0 -> dark square. Same colour.
        self._setup({
            "a1": Piece(WHITE, KING),
            "c1": Piece(WHITE, BISHOP),
            "f4": Piece(BLACK, BISHOP),
            "h8": Piece(BLACK, KING),
        })

        self.assertEqual("draw_insufficient", self.game.state()["status"])

    def test_rook_on_board_is_not_insufficient(self):
        self._setup({
            "a1": Piece(WHITE, KING),
            "h1": Piece(WHITE, ROOK),
            "h8": Piece(BLACK, KING),
        })

        self.assertEqual("active", self.game.state()["status"])

    def test_pawn_on_board_is_not_insufficient(self):
        self._setup({
            "a1": Piece(WHITE, KING),
            "b2": Piece(WHITE, PAWN),
            "h8": Piece(BLACK, KING),
        })

        self.assertEqual("active", self.game.state()["status"])


class FiftyMoveRuleTest(unittest.TestCase):
    def test_halfmove_clock_reaches_100_triggers_draw(self):
        game = ChessGame()
        game.board = {
            "a1": Piece(WHITE, KING),
            "h1": Piece(WHITE, ROOK),
            "e8": Piece(BLACK, KING),
        }
        game.turn = WHITE
        game.halfmove_clock = 99
        game.position_counts = {}
        game._cached_status = None

        # Non-pawn, non-capture move bumps halfmove_clock to 100.
        state = game.move("h1", "h2")

        self.assertEqual(100, state["halfmoveClock"])
        self.assertEqual("draw_fifty_move", state["status"])

    def test_halfmove_clock_resets_on_capture(self):
        game = ChessGame()
        game.move("e2", "e4")
        game.move("d7", "d5")
        # Both are pawn moves -> halfmove_clock is 0.
        self.assertEqual(0, game.halfmove_clock)
        game.move("g1", "f3")
        self.assertEqual(1, game.halfmove_clock)
        game.move("d5", "e4")  # pawn capture
        self.assertEqual(0, game.halfmove_clock)


class ThreefoldRepetitionTest(unittest.TestCase):
    def test_knight_oscillation_triggers_repetition_draw(self):
        game = ChessGame()
        # Two full rounds of Nb1c3, Nb8c6, Nc3b1, Nc6b8 = position-after-move 0
        # gets visited three times (initial setup + two returns).
        for _ in range(2):
            game.move("b1", "c3")
            game.move("b8", "c6")
            game.move("c3", "b1")
            game.move("c6", "b8")

        self.assertEqual("draw_repetition", game.state()["status"])


class EngineFastPathTest(unittest.TestCase):
    """The engine fast-path skips SAN/status, but state must still round-trip."""

    def test_engine_make_then_undo_restores_position(self):
        game = ChessGame()
        before_board = {sq: (p.color, p.kind) for sq, p in game.board.items()}

        record = game.engine_make_move("e2", "e4")

        self.assertEqual(BLACK, game.turn)
        self.assertIn("e4", game.board)
        self.assertNotIn("e2", game.board)
        # SAN intentionally NOT computed by the fast path.
        self.assertEqual("", record.san)

        game.engine_undo()

        after_board = {sq: (p.color, p.kind) for sq, p in game.board.items()}
        self.assertEqual(WHITE, game.turn)
        self.assertEqual(before_board, after_board)
        self.assertEqual([], game.history)

    def test_engine_undo_with_empty_history_is_noop(self):
        game = ChessGame()
        # Should not raise — engine_undo is the silent counterpart of engine_make_move.
        game.engine_undo()
        self.assertEqual(WHITE, game.turn)

    def test_state_exposes_halfmove_clock(self):
        game = ChessGame()
        self.assertIn("halfmoveClock", game.state())
        self.assertEqual(0, game.state()["halfmoveClock"])
        game.move("g1", "f3")  # knight move -> halfmove_clock should bump
        self.assertEqual(1, game.state()["halfmoveClock"])


if __name__ == "__main__":
    unittest.main()
