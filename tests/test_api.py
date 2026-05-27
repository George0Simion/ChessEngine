import unittest


try:
    from app import create_app
except ModuleNotFoundError as exc:
    if exc.name != "flask":
        raise
    create_app = None


@unittest.skipIf(create_app is None, "Flask is not installed")
class ApiTest(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    # ------------------------------------------------------------------
    # State / moves / history (Sprint 1+2 carry-over)
    # ------------------------------------------------------------------

    def test_state_endpoint_returns_initial_board(self):
        response = self.client.get("/api/state")

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertEqual("white", payload["turn"])
        self.assertEqual(32, len(payload["board"]))

    def test_state_endpoint_exposes_session_info(self):
        payload = self.client.get("/api/state").get_json()

        self.assertIn("session", payload)
        self.assertEqual("local", payload["session"]["mode"])
        self.assertIsNone(payload["session"]["botColor"])
        # In local mode the engine field is suppressed.
        self.assertIsNone(payload["session"]["engine"])

    def test_state_endpoint_exposes_halfmove_clock(self):
        payload = self.client.get("/api/state").get_json()
        self.assertEqual(0, payload["halfmoveClock"])

    def test_moves_endpoint_returns_legal_moves_for_selected_piece(self):
        response = self.client.get("/api/moves?from=e2")

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual({"e3", "e4"}, set(payload["moves"]))

    def test_move_endpoint_updates_state(self):
        response = self.client.post("/api/move", json={"from": "e2", "to": "e4"})

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual("black", payload["state"]["turn"])
        self.assertIn("e4", payload["state"]["board"])

    def test_move_endpoint_rejects_invalid_move(self):
        response = self.client.post("/api/move", json={"from": "e2", "to": "e5"})

        self.assertEqual(400, response.status_code)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("Mutarea nu este valida", payload["error"])

    def test_reset_endpoint_restores_initial_state(self):
        self.client.post("/api/move", json={"from": "e2", "to": "e4"})
        response = self.client.post("/api/reset")

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual("white", payload["state"]["turn"])
        self.assertIn("e2", payload["state"]["board"])

    def test_reset_preserves_current_mode(self):
        # Switch to vs-bot, then reset — mode must persist.
        self.client.post(
            "/api/new_game",
            json={"mode": "vs_bot", "botColor": "black"},
        )
        response = self.client.post("/api/reset")

        payload = response.get_json()
        self.assertEqual("vs_bot", payload["state"]["session"]["mode"])
        self.assertEqual("black", payload["state"]["session"]["botColor"])

    def test_new_bot_game_resets_move_history(self):
        self.client.post("/api/move", json={"from": "e2", "to": "e4"})
        self.client.post("/api/move", json={"from": "e7", "to": "e5"})

        response = self.client.post(
            "/api/new_game",
            json={"mode": "vs_bot", "botColor": "black"},
        )

        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual([], payload["state"]["history"])

    def test_move_endpoint_records_history_with_san(self):
        self.client.post("/api/move", json={"from": "e2", "to": "e4"})
        response = self.client.post("/api/move", json={"from": "e7", "to": "e5"})

        payload = response.get_json()
        history = payload["state"]["history"]
        self.assertEqual(2, len(history))
        self.assertEqual("e4", history[0]["san"])
        self.assertEqual("e5", history[1]["san"])

    def test_undo_endpoint_reverts_last_move(self):
        self.client.post("/api/move", json={"from": "e2", "to": "e4"})
        response = self.client.post("/api/undo")

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual("white", payload["state"]["turn"])
        self.assertIn("e2", payload["state"]["board"])
        self.assertEqual([], payload["state"]["history"])

    def test_undo_endpoint_with_no_history_returns_400(self):
        response = self.client.post("/api/undo")
        self.assertEqual(400, response.status_code)
        payload = response.get_json()
        self.assertFalse(payload["ok"])

    def test_move_endpoint_accepts_promotion(self):
        response = self.client.post(
            "/api/move",
            json={"from": "e2", "to": "e4", "promotion": "queen"},
        )
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.get_json()["ok"])

    # ------------------------------------------------------------------
    # New: /api/new_game
    # ------------------------------------------------------------------

    def test_new_game_local_resets_to_default_mode(self):
        # Make a move, then start a new local game — board resets, mode is local.
        self.client.post("/api/move", json={"from": "e2", "to": "e4"})
        response = self.client.post("/api/new_game", json={"mode": "local"})

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual("local", payload["state"]["session"]["mode"])
        self.assertIsNone(payload["state"]["session"]["botColor"])
        self.assertEqual([], payload["state"]["history"])

    def test_new_game_vs_bot_records_session(self):
        response = self.client.post(
            "/api/new_game",
            json={"mode": "vs_bot", "botColor": "black"},
        )
        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        session = payload["state"]["session"]
        self.assertEqual("vs_bot", session["mode"])
        self.assertEqual("black", session["botColor"])
        self.assertEqual("mcts", session["engine"])

    def test_new_game_rejects_unknown_mode(self):
        response = self.client.post("/api/new_game", json={"mode": "battle_royale"})

        self.assertEqual(400, response.status_code)
        self.assertFalse(response.get_json()["ok"])

    def test_new_game_rejects_vs_bot_without_color(self):
        response = self.client.post("/api/new_game", json={"mode": "vs_bot"})

        self.assertEqual(400, response.status_code)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("botColor", payload["error"])

    # ------------------------------------------------------------------
    # New: /api/bot_move
    # ------------------------------------------------------------------

    def test_bot_move_rejected_in_local_mode(self):
        response = self.client.post("/api/bot_move")
        self.assertEqual(400, response.status_code)
        self.assertFalse(response.get_json()["ok"])

    def test_bot_move_rejected_when_not_bots_turn(self):
        # Bot plays Black; it is White's turn initially.
        self.client.post(
            "/api/new_game",
            json={"mode": "vs_bot", "botColor": "black"},
        )
        response = self.client.post("/api/bot_move")

        self.assertEqual(400, response.status_code)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("randul", payload["error"])

    def test_bot_move_plays_a_legal_move(self):
        # Configure bot as White (will move first). MCTS with default params
        # takes up to ~1.5s — acceptable for a single-call smoke test.
        self.client.post(
            "/api/new_game",
            json={"mode": "vs_bot", "botColor": "white"},
        )
        response = self.client.post("/api/bot_move")

        self.assertEqual(200, response.status_code)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(1, len(payload["state"]["history"]))
        self.assertEqual("white", payload["state"]["history"][0]["color"])
        self.assertEqual("black", payload["state"]["turn"])
        # Returned move payload exposes origin/destination as squares.
        self.assertIn("from", payload["move"])
        self.assertIn("to", payload["move"])

    def test_move_endpoint_refuses_when_bot_is_on_turn(self):
        # Bot plays White. Human should NOT be able to push a white move.
        self.client.post(
            "/api/new_game",
            json={"mode": "vs_bot", "botColor": "white"},
        )
        response = self.client.post("/api/move", json={"from": "e2", "to": "e4"})

        self.assertEqual(400, response.status_code)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("bot", payload["error"].lower())


if __name__ == "__main__":
    unittest.main()
