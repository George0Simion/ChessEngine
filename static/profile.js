/* ============================================================
   ChessMate &mdash; profile page.
   - Requires login; gates with a "go home" modal otherwise.
   - Loads /auth/me and /games/history.
   - Renders only persisted chess games (no puzzle attempts).
   ============================================================ */

const TOKEN_KEY = 'chessmate_token';

const $ = (sel) => document.querySelector(sel);
const userChipEl   = $('#user-chip');
const userNameEl   = $('#user-name');
const userRatingEl = $('#user-rating');
const profileName  = $('#profile-name');
const profileRat   = $('#profile-rating');
const profileRD    = $('#profile-rd');
const profileGames = $('#profile-games');
const historyList  = $('#history-list');
const historyEmpty = $('#history-empty');
const logoutBtn    = $('#logout-btn');
const authGate     = $('#auth-gate');

function token() { return localStorage.getItem(TOKEN_KEY); }

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

const RESULT_LABEL = {
  win: 'Win', loss: 'Loss', draw: 'Draw',
  aborted: 'Aborted', in_progress: 'In progress',
};
const REASON_LABEL = {
  checkmate: 'Checkmate', stalemate: 'Stalemate',
  resignation: 'Resignation', timeout: 'Timeout',
  draw_50_move: '50-move rule', draw_insufficient: 'Insufficient material',
  draw_threefold: 'Threefold repetition',
  engine_error: 'Engine error', engine_illegal_move: 'Engine illegal move',
};

function pillForResult(r) {
  const cls = r === 'win' ? 'win' : r === 'loss' ? 'loss' : r === 'draw' ? 'draw' : '';
  return `<span class="result-pill ${cls}">${RESULT_LABEL[r] || r}</span>`;
}

function renderHistory(games) {
  if (!games || games.length === 0) {
    historyEmpty.hidden = false;
    historyList.hidden  = true;
    return;
  }
  historyEmpty.hidden = true;
  historyList.hidden  = false;
  historyList.innerHTML = '';

  for (const g of games) {
    const li = document.createElement('li');
    li.className = 'history-item';
    const reason = g.result_reason ? (REASON_LABEL[g.result_reason] || g.result_reason) : '';
    li.innerHTML = `
      <div class="hi-main">
        <span class="hi-opp">${g.opponent}</span>
        <span class="hi-color">as ${g.user_color}</span>
        ${pillForResult(g.result)}
      </div>
      <div class="hi-meta">
        <span>${g.moves_count} moves</span>
        ${reason ? `<span>&middot; ${reason}</span>` : ''}
        <span>&middot; ${fmtDate(g.created_at)}</span>
      </div>
    `;
    historyList.appendChild(li);
  }
}

async function fetchJson(path) {
  const tk = token();
  const res = await fetch(path, {
    headers: tk ? { Authorization: `Bearer ${tk}` } : {},
  });
  return res.ok ? res.json() : null;
}

async function boot() {
  if (!token()) {
    authGate.hidden = false;
    return;
  }

  const me = await fetchJson('/auth/me');
  if (!me || !me.ok) {
    localStorage.removeItem(TOKEN_KEY);
    authGate.hidden = false;
    return;
  }

  const u = me.user || {};
  userChipEl.hidden = false;
  userNameEl.textContent = u.username || '';
  userRatingEl.textContent = u.rating ? `★ ${u.rating}` : '';
  logoutBtn.hidden = false;

  profileName.textContent  = u.username || '—';
  profileRat.textContent   = u.rating != null ? u.rating : '—';
  profileRD.textContent    = u.rd != null ? u.rd : '—';

  const hist = await fetchJson('/games/history');
  const games = (hist && hist.games) || [];
  profileGames.textContent = games.length;
  renderHistory(games);
}

logoutBtn.addEventListener('click', () => {
  localStorage.removeItem(TOKEN_KEY);
  location.href = '/';
});

boot();
