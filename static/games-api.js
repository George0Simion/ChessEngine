/* ============================================================
   ChessMate — /games/* API helper
   Exposes GamesAPI globally (no build step required).
   Automatically attaches Authorization: Bearer <token> using
   the same localStorage key as the main app.
   ============================================================ */

const GamesAPI = (() => {
  const TOKEN_KEY = 'chessmate_token';

  function _headers() {
    const token = localStorage.getItem(TOKEN_KEY);
    const h = { 'Content-Type': 'application/json' };
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
  }

  async function _call(method, path, body) {
    const opts = { method, headers: _headers() };
    if (body !== undefined) opts.body = JSON.stringify(body);

    const res = await fetch(path, opts);
    let data;
    try {
      data = await res.json();
    } catch {
      const err = new Error(`HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }

    if (!res.ok) {
      const err = new Error((data && data.error) || `HTTP ${res.status}`);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  return {
    hasToken() {
      return !!localStorage.getItem(TOKEN_KEY);
    },

    /** POST /games/bot — create a new bot game.
     *  @param {string} color  "white" | "black" | "random"
     *  @param {number} level  1 | 2 | 3 | 4
     */
    createBotGame(color, level) {
      return _call('POST', '/games/bot', { color, level: Number(level) });
    },

    /** GET /games/<id> — fetch current state. */
    getGame(gameId) {
      return _call('GET', `/games/${gameId}`);
    },

    /** POST /games/<id>/move — submit a UCI move ("e2e4"). */
    submitMove(gameId, move) {
      return _call('POST', `/games/${gameId}/move`, { move });
    },

    /** POST /games/<id>/resign — resign the game. */
    resignGame(gameId) {
      return _call('POST', `/games/${gameId}/resign`);
    },
  };
})();
