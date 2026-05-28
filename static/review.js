/* ============================================================
   ChessMate — Game Review & Analysis page.
   Loads /games/<id>/review-data, renders a FEN-based board for
   each ply, and optionally fetches /games/<id>/analyze to label
   moves with categories (Best, Mistake, Blunder, ...).
   ============================================================ */

const TOKEN_KEY = 'chessmate_token';
const FILES = ['a','b','c','d','e','f','g','h'];
const RANKS_TOP_DOWN = [8,7,6,5,4,3,2,1];
const PIECE_GLYPHS = {
  P: '♟', N: '♞', B: '♝', R: '♜', Q: '♛', K: '♚',
};

const CATEGORY_LABEL = {
  Best: 'Best', Excellent: 'Excellent', Good: 'Good',
  Inaccuracy: 'Inaccuracy', Mistake: 'Mistake', Blunder: 'Blunder',
  Brilliant: 'Brilliant',
};

// ----- State -----
let gameId = null;
let plies = [];          // [{ ply, color, uci, san, fen_before, fen_after }]
let startingFen = '';
let meta = {};
let currentIndex = 0;    // 0 = starting position; 1..plies.length = after that ply
let analysis = null;     // { moves: [...], summary: {...} }
let isFlipped = false;
let localReviewMoves = [];

// ----- DOM -----
const squaresLayer = document.querySelector('#squares-layer');
const piecesLayer = document.querySelector('#pieces-layer');
const coordsFiles = document.querySelector('#coords-files');
const coordsRanks = document.querySelector('#coords-ranks');
const navStart = document.querySelector('#nav-start');
const navPrev  = document.querySelector('#nav-prev');
const navNext  = document.querySelector('#nav-next');
const navEnd   = document.querySelector('#nav-end');
const navFlip  = document.querySelector('#nav-flip');
const navStatus = document.querySelector('#nav-status');
const nameTop = document.querySelector('#name-top');
const nameBottom = document.querySelector('#name-bottom');
const movesList = document.querySelector('#moves-list');
const reviewResult = document.querySelector('#review-result');
const reviewMeta = document.querySelector('#review-meta');
const reviewSummaryMini = document.querySelector('#review-summary-mini');
const analyzeCta = document.querySelector('#analyze-cta');
const analyzeBtn = document.querySelector('#analyze-btn');
const analyzeProgress = document.querySelector('#analyze-progress');
const analysisPanel = document.querySelector('#analysis-panel');
const analysisSummary = document.querySelector('#analysis-summary');
const analysisCurrent = document.querySelector('#analysis-current');
const reviewTitle = document.querySelector('#review-title');
const reviewEval = document.querySelector('#review-eval');
const reviewEvalScore = document.querySelector('#review-eval-score');
const reviewEvalBlack = document.querySelector('#review-eval-black');
const reviewEvalWhite = document.querySelector('#review-eval-white');

// ----- Board scaffold -----
function buildScaffold() {
  squaresLayer.innerHTML = '';
  for (let r = 0; r < 8; r++) {
    for (let f = 0; f < 8; f++) {
      const sq = document.createElement('div');
      const rank = isFlipped ? r + 1 : 8 - r;
      const file = isFlipped ? FILES[7 - f] : FILES[f];
      sq.className = 'square ' + (((r + f) & 1) ? 'dark' : 'light');
      sq.dataset.square = file + rank;
      squaresLayer.appendChild(sq);
    }
  }
  coordsFiles.innerHTML = '';
  coordsRanks.innerHTML = '';
  const filesOrder = isFlipped ? [...FILES].reverse() : FILES;
  const ranksOrder = isFlipped ? [1,2,3,4,5,6,7,8] : RANKS_TOP_DOWN;
  for (const f of filesOrder) {
    const el = document.createElement('span');
    el.textContent = f;
    coordsFiles.appendChild(el);
  }
  for (const r of ranksOrder) {
    const el = document.createElement('span');
    el.textContent = r;
    coordsRanks.appendChild(el);
  }
}

function fenToBoard(fen) {
  // Returns { "e4": {color: "white", glyph: "♟"}, ... }
  const placement = fen.split(' ')[0];
  const rows = placement.split('/');
  const out = {};
  for (let r = 0; r < 8; r++) {
    let file = 0;
    for (const ch of rows[r]) {
      if (/\d/.test(ch)) { file += Number(ch); continue; }
      const sq = FILES[file] + (8 - r);
      const color = ch === ch.toUpperCase() ? 'white' : 'black';
      const glyph = PIECE_GLYPHS[ch.toUpperCase()] || '?';
      out[sq] = { color, glyph };
      file++;
    }
  }
  return out;
}

function squareTranslate(square) {
  const file = FILES.indexOf(square[0]);
  const rank = Number(square[1]) - 1;
  const fx = isFlipped ? 7 - file : file;
  const fy = isFlipped ? rank : 7 - rank;
  return { tx: fx * 100, ty: fy * 100 };
}

function renderBoard(fen) {
  piecesLayer.innerHTML = '';
  const board = fenToBoard(fen);
  for (const [sq, { color, glyph }] of Object.entries(board)) {
    const { tx, ty } = squareTranslate(sq);
    const el = document.createElement('div');
    el.className = `piece ${color}`;
    el.textContent = glyph;
    el.style.transform = `translate(${tx}%, ${ty}%)`;
    piecesLayer.appendChild(el);
  }
  // Highlight last move squares
  for (const s of squaresLayer.querySelectorAll('.square')) {
    s.classList.remove('last-from', 'last-to');
  }
  if (currentIndex > 0) {
    const p = plies[currentIndex - 1];
    const from = p.uci.slice(0, 2);
    const to = p.uci.slice(2, 4);
    const fromEl = squaresLayer.querySelector(`[data-square="${from}"]`);
    const toEl = squaresLayer.querySelector(`[data-square="${to}"]`);
    if (fromEl) fromEl.classList.add('last-from');
    if (toEl) toEl.classList.add('last-to');
  }
}

// ----- Move list -----
function renderMovesList() {
  movesList.innerHTML = '';
  const pairs = [];
  let i = 0;
  if (plies.length > 0 && plies[0].color === 'black') {
    pairs.push({ number: 1, white: null, black: plies[0] });
    i = 1;
  }
  let moveNumber = pairs.length ? 2 : 1;
  for (; i < plies.length; i += 2) {
    pairs.push({ number: moveNumber++, white: plies[i], black: plies[i + 1] || null });
  }

  for (const { number, white, black } of pairs) {
    const li = document.createElement('li');
    const num = document.createElement('span');
    num.className = 'ply-num';
    num.textContent = `${number}.`;
    li.appendChild(num);
    li.appendChild(renderPlyCell(white));
    li.appendChild(renderPlyCell(black));
    movesList.appendChild(li);
  }
  updateMovesActive();
}

function renderPlyCell(p) {
  const span = document.createElement('span');
  if (!p) { span.className = 'ply'; return span; }
  span.className = 'ply review-ply';
  span.dataset.ply = String(p.ply);
  span.textContent = p.san;
  if (analysis) {
    const a = analysis.moves[p.ply - 1];
    if (a) {
      const pill = document.createElement('span');
      pill.className = `move-cat-pill cat-${a.category.toLowerCase()}`;
      pill.textContent = catShort(a.category);
      span.appendChild(pill);
    }
  }
  span.addEventListener('click', () => goTo(p.ply));
  return span;
}

function catShort(category) {
  return ({
    Best: '✓', Excellent: '!', Good: '·', Inaccuracy: '?!',
    Mistake: '?', Blunder: '??', Brilliant: '!!',
  })[category] || '·';
}

function updateMovesActive() {
  for (const cell of movesList.querySelectorAll('.review-ply')) {
    const ply = Number(cell.dataset.ply);
    cell.classList.toggle('current', ply === currentIndex);
  }
  navStatus.textContent = `${currentIndex} / ${plies.length}`;
  navPrev.disabled  = currentIndex <= 0;
  navStart.disabled = currentIndex <= 0;
  navNext.disabled  = currentIndex >= plies.length;
  navEnd.disabled   = currentIndex >= plies.length;
}

// ----- Navigation -----
function goTo(index) {
  currentIndex = Math.max(0, Math.min(plies.length, index));
  const fen = currentIndex === 0 ? startingFen : plies[currentIndex - 1].fen_after;
  renderBoard(fen);
  updateMovesActive();
  renderAnalysisCurrent();
  // Scroll active move into view
  const active = movesList.querySelector('.review-ply.current');
  if (active) active.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

navStart.addEventListener('click', () => goTo(0));
navPrev.addEventListener('click',  () => goTo(currentIndex - 1));
navNext.addEventListener('click',  () => goTo(currentIndex + 1));
navEnd.addEventListener('click',   () => goTo(plies.length));
navFlip.addEventListener('click', () => {
  isFlipped = !isFlipped;
  buildScaffold();
  applyPlayerNames();
  goTo(currentIndex);
});

document.addEventListener('keydown', (e) => {
  if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
  if (e.key === 'ArrowLeft')  { e.preventDefault(); goTo(currentIndex - 1); }
  if (e.key === 'ArrowRight') { e.preventDefault(); goTo(currentIndex + 1); }
  if (e.key === 'Home')       { e.preventDefault(); goTo(0); }
  if (e.key === 'End')        { e.preventDefault(); goTo(plies.length); }
});

// ----- Player name placement (respects flip) -----
function applyPlayerNames() {
  const w = meta.white_name || 'White';
  const b = meta.black_name || 'Black';
  if (isFlipped) {
    nameTop.textContent = w;
    nameBottom.textContent = b;
  } else {
    nameTop.textContent = b;
    nameBottom.textContent = w;
  }
}

// ----- Result + meta header -----
const REASON_LABEL = {
  checkmate: 'Checkmate', stalemate: 'Stalemate', resignation: 'Resignation',
  timeout: 'Timeout', draw_50_move: '50-move rule',
  draw_insufficient: 'Insufficient material', draw_threefold: 'Threefold Repetition',
  abandoned: 'Abandoned', engine_error: 'Engine error',
};

function applyHeader() {
  const winner =
    meta.status === 'white_win' ? 'White wins'
    : meta.status === 'black_win' ? 'Black wins'
    : meta.status === 'draw' ? 'Draw'
    : meta.status === 'aborted' ? 'Aborted'
    : 'In progress';
  const reasonText = meta.result_reason
    ? (REASON_LABEL[meta.result_reason] || meta.result_reason.replace(/_/g, ' '))
    : '';
  const reason = reasonText ? ` · ${reasonText}` : '';
  reviewResult.textContent = `${winner}${reason}`;
  const date = meta.created_at ? new Date(meta.created_at).toLocaleDateString() : '';
  const modeLabel = meta.mode === 'bot' ? 'Bot game' : meta.mode === 'online' ? 'Online game' : 'Game';
  const level = (meta.mode === 'bot' && meta.bot_level) ? ` · Level ${meta.bot_level}` : '';
  reviewMeta.textContent = `${modeLabel}${level} · ${plies.length} moves · ${date}`;
  const title = `${meta.white_name || 'White'} vs ${meta.black_name || 'Black'}`;
  if (reviewTitle) reviewTitle.textContent = title;
  document.title = `${title} — Review`;
}

function isActiveReview() {
  return !meta.status || meta.status === 'active';
}

function evalFromMove(a, field, mateField) {
  if (!a) return null;
  const sideMultiplier = a.color === 'white' ? 1 : -1;
  const cp = a[field];
  const mate = a[mateField];
  return {
    cp: cp == null ? null : sideMultiplier * cp,
    mate: mate == null ? null : sideMultiplier * mate,
  };
}

function evaluationForCurrentPosition() {
  if (!analysis || !Array.isArray(analysis.moves) || analysis.moves.length === 0) {
    return null;
  }
  if (currentIndex === 0) {
    return evalFromMove(analysis.moves[0], 'eval_before', 'mate_before');
  }
  return evalFromMove(analysis.moves[currentIndex - 1], 'eval_after', 'mate_after');
}

function whiteShareForEval(ev) {
  if (!ev) return 50;
  if (ev.mate != null) {
    return ev.mate > 0 ? 96 : 4;
  }
  const cp = Math.max(-1800, Math.min(1800, ev.cp || 0));
  return 50 + Math.tanh(cp / 650) * 45;
}

function evalScoreText(ev) {
  if (!ev) return '0.00';
  if (ev.mate != null) {
    const side = ev.mate > 0 ? 'White' : 'Black';
    return `${side}\nM${Math.abs(ev.mate)}`;
  }
  const cp = ev.cp || 0;
  if (Math.abs(cp) < 10) return '0.00';
  const side = cp > 0 ? 'White' : 'Black';
  return `${side}\n+${(Math.abs(cp) / 100).toFixed(2)}`;
}

function renderEvalBar() {
  if (!reviewEval || !reviewEvalWhite || !reviewEvalBlack || !reviewEvalScore) return;
  if (!analysis || isActiveReview()) {
    reviewEval.hidden = true;
    return;
  }

  const ev = evaluationForCurrentPosition();
  if (!ev) {
    reviewEval.hidden = true;
    return;
  }

  const whiteShare = Math.max(4, Math.min(96, whiteShareForEval(ev)));
  reviewEvalWhite.style.height = `${whiteShare}%`;
  reviewEvalBlack.style.height = `${100 - whiteShare}%`;
  reviewEvalScore.textContent = evalScoreText(ev);
  reviewEvalScore.classList.toggle('white-adv', ev.mate != null ? ev.mate > 0 : (ev.cp || 0) > 10);
  reviewEvalScore.classList.toggle('black-adv', ev.mate != null ? ev.mate < 0 : (ev.cp || 0) < -10);
  reviewEvalScore.classList.toggle('equal', ev.mate == null && Math.abs(ev.cp || 0) <= 10);
  reviewEval.hidden = false;
}

function moveQuality(a) {
  const cpLoss = a && a.cp_loss != null ? Number(a.cp_loss) : null;
  const cat = a ? a.category : '';
  const isOpening = a && a.ply <= 10;

  if (cat === 'Brilliant' && !isOpening) {
    return { key: 'siuuuu', label: 'Siuuuu!!! move', detail: 'A brilliant idea that keeps or improves the advantage.' };
  }
  if (cpLoss === 0 || (cpLoss != null && cpLoss <= 10)) {
    return { key: 'great', label: 'Great move', detail: 'Keeps the advantage almost perfectly.' };
  }
  if (cpLoss != null && cpLoss <= 60) {
    return { key: 'great', label: 'Great move', detail: `Loses only ${(cpLoss / 100).toFixed(2)} pawns of advantage.` };
  }
  if (cpLoss != null && cpLoss <= 120) {
    return { key: 'decent', label: 'Decent move', detail: `Gives up about ${(cpLoss / 100).toFixed(2)} pawns of advantage.` };
  }
  if (cpLoss != null && cpLoss <= 250) {
    return { key: 'bad', label: 'Bad move', detail: `Drops ${(cpLoss / 100).toFixed(2)} pawns from the position.` };
  }
  if (cat === 'Best' || cat === 'Excellent') {
    return { key: 'great', label: 'Great move', detail: 'Keeps the position under control.' };
  }
  if (cat === 'Good' || cat === 'Inaccuracy') {
    return { key: 'decent', label: 'Decent move', detail: 'The position remains playable.' };
  }
  if (cat === 'Mistake') {
    return { key: 'bad', label: 'Bad move', detail: 'The advantage drops noticeably.' };
  }
  return { key: 'blunder', label: 'Blunder', detail: 'Loses a lot of the position evaluation.' };
}

// ----- Analysis -----
function renderAnalysisSummary() {
  if (!analysis) {
    analysisPanel.hidden = true;
    reviewSummaryMini.textContent = '';
    renderEvalBar();
    return;
  }
  analysisPanel.hidden = false;
  const s = analysis.summary || {};
  const order = ['Brilliant', 'Best', 'Excellent', 'Good', 'Inaccuracy', 'Mistake', 'Blunder'];
  analysisSummary.innerHTML = order
    .map((cat) => {
      const n = s[cat] || 0;
      if (n === 0 && !(cat === 'Best' || cat === 'Blunder')) return '';
      return `<span class="cat-stat cat-${cat.toLowerCase()}">
        <span class="cat-stat-n">${n}</span>
        <span class="cat-stat-l">${cat}</span>
      </span>`;
    })
    .join('');
  const totalImportant = (s.Mistake || 0) + (s.Blunder || 0) + (s.Inaccuracy || 0);
  reviewSummaryMini.textContent = totalImportant ? `${totalImportant} issues` : 'clean';
}

function renderAnalysisCurrent() {
  renderEvalBar();
  if (!analysis) { analysisCurrent.innerHTML = ''; return; }
  if (currentIndex === 0) {
    analysisCurrent.innerHTML = '<p class="analysis-empty">Use ◀ ▶ to step through.</p>';
    return;
  }
  const a = analysis.moves[currentIndex - 1];
  if (!a) { analysisCurrent.innerHTML = ''; return; }
  const evalStr = (v) => v == null ? '—' : (v > 0 ? `+${(v/100).toFixed(2)}` : (v/100).toFixed(2));
  const cpLoss = a.cp_loss == null ? '' : ` · cp loss ${a.cp_loss}`;
  const bestLine = (a.best_line || []).slice(0, 4).join(' ');
  const quality = moveQuality(a);
  analysisCurrent.innerHTML = `
    <p class="ac-played">
      <span class="ac-num">${a.ply}.</span>
      <span class="ac-san">${a.san}</span>
      <span class="move-cat-pill cat-${a.category.toLowerCase()}">${CATEGORY_LABEL[a.category]}</span>
    </p>
    <div class="move-quality-card quality-${quality.key}">
      <span class="move-quality-label">${quality.label}</span>
      <span class="move-quality-detail">${quality.detail}</span>
    </div>
    <p class="ac-row"><span class="ac-key">Best</span><span class="ac-val">${a.best_move || '—'}</span></p>
    <p class="ac-row"><span class="ac-key">Eval</span><span class="ac-val">${evalStr(a.eval_before)} → ${evalStr(a.eval_after)}${cpLoss}</span></p>
    ${bestLine ? `<p class="ac-row"><span class="ac-key">Line</span><span class="ac-val mono">${bestLine}</span></p>` : ''}
  `;
}

async function loadAnalysis() {
  try {
    const res = await authFetch(`/games/${gameId}/analysis`);
    if (res && res.ok) {
      analysis = await res.json();
      analyzeCta.hidden = true;
      renderAnalysisSummary();
      renderMovesList();
      renderAnalysisCurrent();
      return true;
    }
  } catch (_) {}
  return false;
}

async function runAnalysis() {
  analyzeBtn.disabled = true;
  analyzeProgress.hidden = false;
  analyzeProgress.textContent = `Analyzing ${plies.length} moves…`;
  try {
    const res = isLocalReview
      ? await fetch('/games/replay/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ moves: localReviewMoves }),
        })
      : await authFetch(`/games/${gameId}/analyze`, { method: 'POST' });
    const data = await res.json();
    if (!data || !data.ok) {
      analyzeProgress.textContent = `Failed: ${data && data.error ? data.error : 'unknown error'}`;
      analyzeBtn.disabled = false;
      return;
    }
    analysis = data;
    analyzeCta.hidden = true;
    renderAnalysisSummary();
    renderMovesList();
    renderAnalysisCurrent();
  } catch (err) {
    analyzeProgress.textContent = `Failed: ${err.message}`;
    analyzeBtn.disabled = false;
  }
}

analyzeBtn.addEventListener('click', runAnalysis);

// ----- Fetch helpers -----
function authFetch(url, init = {}) {
  const tk = localStorage.getItem(TOKEN_KEY);
  const headers = Object.assign({}, init.headers, tk ? { Authorization: `Bearer ${tk}` } : {});
  return fetch(url, { ...init, headers });
}

// ----- Boot -----
let isLocalReview = false;

function gameIdFromUrl() {
  const m = location.pathname.match(/\/games\/(\d+)\/review/);
  return m ? Number(m[1]) : null;
}

async function loadSavedGame() {
  const res = await authFetch(`/games/${gameId}/review-data`);
  if (!res.ok) {
    document.body.innerHTML = `<p style="padding:24px">Cannot load game (${res.status}).</p>`;
    return null;
  }
  return res.json();
}

async function loadLocalGame() {
  // Local (unsaved) games: moves stashed in sessionStorage by the play page.
  let stash = null;
  try {
    stash = JSON.parse(sessionStorage.getItem('chessmate_local_review') || 'null');
  } catch (_) { /* ignore */ }
  if (!stash || !Array.isArray(stash.moves) || stash.moves.length === 0) {
    document.body.innerHTML = '<p style="padding:24px">No local game to review.</p>';
    return null;
  }
  localReviewMoves = stash.moves.map((m) => String(m));
  const res = await fetch('/games/replay', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ moves: stash.moves, meta: stash.meta || {} }),
  });
  if (!res.ok) {
    document.body.innerHTML = `<p style="padding:24px">Cannot replay local game (${res.status}).</p>`;
    return null;
  }
  return res.json();
}

async function boot() {
  gameId = gameIdFromUrl();
  isLocalReview = !gameId;

  buildScaffold();

  const data = isLocalReview ? await loadLocalGame() : await loadSavedGame();
  if (!data) return;
  if (!data.ok && !data.plies) {
    document.body.innerHTML = `<p style="padding:24px">Cannot load game: ${data.error || 'unknown error'}</p>`;
    return;
  }

  plies = data.plies || [];
  startingFen = data.starting_fen;
  meta = data.meta || {};

  // Flip so the user's pieces sit at the bottom.
  if (meta.user_color === 'black') {
    isFlipped = true;
    buildScaffold();
  }

  applyHeader();
  applyPlayerNames();
  renderMovesList();
  goTo(plies.length); // start at the end of the game

  // Engine analysis is only offered for finished games. Saved games use the
  // cached DB-backed endpoint; local games send their stashed moves statelessly.
  const isActive = !meta.status || meta.status === 'active';
  if (isActive) {
    analyzeCta.hidden = true;
  } else if (isLocalReview) {
    analyzeCta.hidden = false;
    if ((new URLSearchParams(location.search)).get('analyze') === '1') {
      await runAnalysis();
    }
  } else if (data.analysis_ready || (new URLSearchParams(location.search)).get('analyze') === '1') {
    const had = await loadAnalysis();
    if (!had && (new URLSearchParams(location.search)).get('analyze') === '1') {
      await runAnalysis();
    }
  }
}

boot();
