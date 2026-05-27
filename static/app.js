/* ============================================================
   ChessMate — frontend
   - FLIP-style piece animations
   - Move history, captured pieces, undo/flip
   - Promotion + endgame modals
   - Game-mode selection (1v1 local / vs bot) with auto bot moves
   ============================================================ */

const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];
const RANKS_TOP_DOWN = [8, 7, 6, 5, 4, 3, 2, 1]; // visual order, white at bottom
// We use the filled (traditionally "black") Unicode glyphs for BOTH colors and
// let CSS color them — outlined "white" glyphs render inconsistently across
// browsers at small sizes.
const PIECE_SYMBOLS = {
  white: { king: "\u265A", queen: "\u265B", rook: "\u265C", bishop: "\u265D", knight: "\u265E", pawn: "\u265F" },
  black: { king: "\u265A", queen: "\u265B", rook: "\u265C", bishop: "\u265D", knight: "\u265E", pawn: "\u265F" },
};
const PIECE_VALUES = { pawn: 1, knight: 3, bishop: 3, rook: 5, queen: 9, king: 0 };

// ----- Application state -----
let lastState = null;          // last server state we rendered
let selectedSquare = null;
let legalMoves = [];
let pendingPromotion = null;   // { from, to } awaiting user's choice
let isFlipped = false;         // board orientation (true => black at bottom)
let endgameSeen = false;       // suppress repeat endgame modals after a single render
let pieceMap = {};             // square -> piece DOM id
let pieceById = {};            // id -> { square, color, kind, element }
let pieceIdSeq = 0;
let interactionLocked = false; // brief lock while a move animates
let botPending = false;        // a /api/bot_move call is in-flight or queued
// Mode-select draft state (mirrors UI selection inside the modal)
let modeDraft = { mode: "local", color: "white" };

// ----- DOM -----
const boardEl = document.querySelector("#board");
const squaresLayer = document.querySelector("#squares-layer");
const piecesLayer = document.querySelector("#pieces-layer");
const coordsFiles = document.querySelector("#coords-files");
const coordsRanks = document.querySelector("#coords-ranks");
const messageEl = document.querySelector("#message");
const turnPill = document.querySelector("#turn-pill");
const turnText = document.querySelector("#turn-text");
const moveCountBadge = document.querySelector("#move-count");
const movesList = document.querySelector("#moves-list");
const movesEmpty = document.querySelector("#moves-empty");
const modeButton = document.querySelector("#mode-button");
const modeButtonLabel = document.querySelector("#mode-button-label");
const undoButton = document.querySelector("#undo-button");
const flipButton = document.querySelector("#flip-button");
const resetButton = document.querySelector("#reset-button");
const playerTopCard = document.querySelector("#player-top");
const playerBottomCard = document.querySelector("#player-bottom");
const capturedByWhite = document.querySelector("#captured-by-white");
const capturedByBlack = document.querySelector("#captured-by-black");
const promoModal = document.querySelector("#promo-modal");
const promoChoices = document.querySelector("#promo-choices");
const endgameModal = document.querySelector("#endgame-modal");
const endgameTitle = document.querySelector("#endgame-title");
const endgameText = document.querySelector("#endgame-text");
const endgameIcon = document.querySelector("#endgame-icon");
const endgameClose = document.querySelector("#endgame-close");
const endgameReset = document.querySelector("#endgame-reset");
const modeModal = document.querySelector("#mode-modal");
const modeChoicesWrap = document.querySelector("#mode-choices");
const modeOptions = document.querySelector("#mode-options");
const colorChoicesWrap = document.querySelector("#color-choices");
const modeStart = document.querySelector("#mode-start");
const modeCancel = document.querySelector("#mode-cancel");
const botThinking = document.querySelector("#bot-thinking");

// ----- Helpers -----

function setMessage(text, kind = "error") {
  messageEl.textContent = text || "";
  messageEl.className = "message" + (text ? " " + kind : "");
}

function squareToCoords(square) {
  return { fileIdx: FILES.indexOf(square[0]), rankIdx: Number(square[1]) - 1 };
}

function isDarkSquare(square) {
  const { fileIdx, rankIdx } = squareToCoords(square);
  return (fileIdx + rankIdx) % 2 === 0;
}

function piecePositionPercent(square) {
  const { fileIdx, rankIdx } = squareToCoords(square);
  const fx = isFlipped ? 7 - fileIdx : fileIdx;
  const fy = isFlipped ? rankIdx : 7 - rankIdx;
  return { tx: fx * 100, ty: fy * 100 };
}

function setPieceTransform(element, square, immediate = false) {
  const { tx, ty } = piecePositionPercent(square);
  if (immediate) {
    const prev = element.style.transition;
    element.style.transition = "none";
    element.style.transform = `translate(${tx}%, ${ty}%)`;
    void element.offsetWidth;
    element.style.transition = prev;
  } else {
    element.style.transform = `translate(${tx}%, ${ty}%)`;
  }
  element.style.setProperty("--tx", `${tx}%`);
  element.style.setProperty("--ty", `${ty}%`);
}

function createPieceElement(piece, square) {
  const el = document.createElement("div");
  el.className = `piece ${piece.color} ${piece.kind}`;
  el.textContent = PIECE_SYMBOLS[piece.color][piece.kind];
  piecesLayer.appendChild(el);
  setPieceTransform(el, square, true);
  return el;
}

function newPiece(square, piece) {
  const id = `p${pieceIdSeq++}`;
  const element = createPieceElement(piece, square);
  pieceMap[square] = id;
  pieceById[id] = { square, color: piece.color, kind: piece.kind, element };
  return id;
}

function removePieceById(id) {
  const p = pieceById[id];
  if (!p) return;
  if (pieceMap[p.square] === id) delete pieceMap[p.square];
  p.element.classList.add("captured-out");
  setTimeout(() => p.element.remove(), 220);
  delete pieceById[id];
}

function clearPieces() {
  for (const id of Object.keys(pieceById)) {
    pieceById[id].element.remove();
  }
  pieceMap = {};
  pieceById = {};
  pieceIdSeq = 0;
}

// ----- Board scaffolding -----

function buildBoardScaffold() {
  rebuildSquaresLayout();
  rebuildCoords();
}

function rebuildCoords() {
  coordsFiles.innerHTML = "";
  const fileOrder = isFlipped ? [...FILES].reverse() : FILES;
  for (const f of fileOrder) {
    const span = document.createElement("span");
    span.textContent = f;
    coordsFiles.appendChild(span);
  }
  coordsRanks.innerHTML = "";
  const rankOrder = isFlipped ? [1, 2, 3, 4, 5, 6, 7, 8] : RANKS_TOP_DOWN;
  for (const r of rankOrder) {
    const span = document.createElement("span");
    span.textContent = r;
    coordsRanks.appendChild(span);
  }
}

function rebuildSquaresLayout() {
  squaresLayer.innerHTML = "";
  const ranks = isFlipped ? [1, 2, 3, 4, 5, 6, 7, 8] : RANKS_TOP_DOWN;
  const files = isFlipped ? [...FILES].reverse() : FILES;
  for (const rank of ranks) {
    for (const file of files) {
      const square = `${file}${rank}`;
      const tile = document.createElement("button");
      tile.type = "button";
      tile.className = `square ${isDarkSquare(square) ? "dark" : "light"}`;
      tile.dataset.square = square;
      tile.setAttribute("aria-label", square);
      tile.addEventListener("click", () => handleSquareClick(square));
      squaresLayer.appendChild(tile);
    }
  }
}

// ----- Diff & apply moves to piece layer -----

function rebuildAllPieces(board) {
  clearPieces();
  for (const [square, piece] of Object.entries(board)) {
    newPiece(square, piece);
  }
}

function applyHistoryRecord(record, oldBoard) {
  const { from, to, capturedKind, castling, promotionKind, pieceKind } = record;

  if (capturedKind) {
    let captureSquare = to;
    if (pieceKind === "pawn" && from[0] !== to[0] && !oldBoard[to]) {
      captureSquare = to[0] + from[1];
    }
    const capturedId = pieceMap[captureSquare];
    if (capturedId) removePieceById(capturedId);
  }

  const movingId = pieceMap[from];
  if (movingId) {
    delete pieceMap[from];
    pieceMap[to] = movingId;
    pieceById[movingId].square = to;
    setPieceTransform(pieceById[movingId].element, to);
    if (promotionKind) {
      const p = pieceById[movingId];
      p.kind = promotionKind;
      p.element.textContent = PIECE_SYMBOLS[p.color][promotionKind];
      p.element.classList.add("promoting");
      setTimeout(() => p.element.classList.remove("promoting"), 380);
    }
  }

  if (castling) {
    const rank = from[1];
    const rookFrom = (castling === "K" ? "h" : "a") + rank;
    const rookTo   = (castling === "K" ? "f" : "d") + rank;
    const rookId = pieceMap[rookFrom];
    if (rookId) {
      delete pieceMap[rookFrom];
      pieceMap[rookTo] = rookId;
      pieceById[rookId].square = rookTo;
      setPieceTransform(pieceById[rookId].element, rookTo);
    }
  }
}

function projectBoard(prev, record) {
  const next = { ...prev };
  const { from, to, capturedKind, castling, promotionKind, pieceKind } = record;
  if (capturedKind) {
    if (pieceKind === "pawn" && from[0] !== to[0] && !prev[to]) {
      delete next[to[0] + from[1]];
    }
  }
  next[to] = next[from];
  delete next[from];
  if (promotionKind) {
    next[to] = { ...next[to], kind: promotionKind, symbol: PIECE_SYMBOLS[next[to].color][promotionKind] };
  }
  if (castling) {
    const rank = from[1];
    const rookFrom = (castling === "K" ? "h" : "a") + rank;
    const rookTo   = (castling === "K" ? "f" : "d") + rank;
    next[rookTo] = next[rookFrom];
    delete next[rookFrom];
  }
  return next;
}

// ----- Render: status, moves, captured, highlights -----

function renderStatus(state) {
  const colorRo = state.turn === "white" ? "Albe" : "Negre";
  turnText.textContent = state.status === "active" ? `Tura: ${colorRo}` : labelForStatus(state);
  turnPill.dataset.turn = state.turn;
  const whiteCard = isFlipped ? playerTopCard : playerBottomCard;
  const blackCard = isFlipped ? playerBottomCard : playerTopCard;
  whiteCard.classList.toggle("active", state.turn === "white" && state.status === "active");
  blackCard.classList.toggle("active", state.turn === "black" && state.status === "active");

  // Swap player labels by current orientation. In vs-bot mode replace the
  // bot's display name so it's clear which side the engine controls.
  const session = state.session || {};
  const botColor = session.mode === "vs_bot" ? session.botColor : null;
  const whiteName = botColor === "white" ? "BOT" : "PESSI";
  const blackName = botColor === "black" ? "BOT" : "RONALDO";
  const topName  = playerTopCard.querySelector(".player-name");
  const topColor = playerTopCard.querySelector(".player-color");
  const topDot   = playerTopCard.querySelector(".player-dot");
  const botName  = playerBottomCard.querySelector(".player-name");
  const botColorEl = playerBottomCard.querySelector(".player-color");
  const botDot   = playerBottomCard.querySelector(".player-dot");
  if (isFlipped) {
    topName.textContent = whiteName;  topColor.textContent = "Albe";  topDot.className = "player-dot white";
    botName.textContent = blackName;  botColorEl.textContent = "Negre"; botDot.className = "player-dot black";
  } else {
    topName.textContent = blackName;  topColor.textContent = "Negre"; topDot.className = "player-dot black";
    botName.textContent = whiteName;  botColorEl.textContent = "Albe";  botDot.className = "player-dot white";
  }
}

function labelForStatus(state) {
  if (state.status === "checkmate") {
    const winner = state.winnerLabel || (state.winner === "white" ? "Albe" : "Negre");
    return `Sah-mat — ${winner} castiga`;
  }
  if (state.status === "stalemate") return "Pat — remiza";
  if (state.status === "draw_insufficient") return "Remiza — material insuficient";
  if (state.status === "draw_fifty_move") return "Remiza — regula celor 50 de mutari";
  if (state.status === "draw_repetition") return "Remiza — repetitie triplа";
  return `Tura: ${state.turn === "white" ? "Albe" : "Negre"}`;
}

function renderMoves(state) {
  const history = state.history || [];
  moveCountBadge.textContent = history.length;
  movesEmpty.style.display = history.length === 0 ? "block" : "none";
  movesList.innerHTML = "";

  const pairs = [];
  for (let i = 0; i < history.length; i += 2) {
    pairs.push({ number: history[i].number, white: history[i], black: history[i + 1] || null });
  }

  for (let i = 0; i < pairs.length; i++) {
    const { number, white, black } = pairs[i];
    const li = document.createElement("li");
    const isLatestRow = i === pairs.length - 1;

    const num = document.createElement("span");
    num.className = "ply-num";
    num.textContent = `${number}.`;
    li.appendChild(num);

    const w = document.createElement("span");
    w.className = "ply" + (isLatestRow && !black ? " latest" : "");
    w.textContent = white.san;
    li.appendChild(w);

    const b = document.createElement("span");
    if (black) {
      b.className = "ply" + (isLatestRow ? " latest" : "");
      b.textContent = black.san;
    } else {
      b.className = "ply empty";
      b.textContent = "...";
    }
    li.appendChild(b);

    movesList.appendChild(li);
  }
  movesList.scrollTop = movesList.scrollHeight;
}

function renderCaptured(state) {
  const captured = state.captured || { white: [], black: [] };
  capturedByBlack.innerHTML = "";
  for (const kind of sortByValue(captured.white)) {
    const span = document.createElement("span");
    span.className = "captured-piece white";
    span.textContent = PIECE_SYMBOLS.white[kind];
    capturedByBlack.appendChild(span);
  }
  capturedByWhite.innerHTML = "";
  for (const kind of sortByValue(captured.black)) {
    const span = document.createElement("span");
    span.className = "captured-piece black";
    span.textContent = PIECE_SYMBOLS.black[kind];
    capturedByWhite.appendChild(span);
  }
  const whiteScore = captured.black.reduce((s, k) => s + (PIECE_VALUES[k] || 0), 0);
  const blackScore = captured.white.reduce((s, k) => s + (PIECE_VALUES[k] || 0), 0);
  if (whiteScore > blackScore) {
    const badge = document.createElement("span");
    badge.className = "captured-advantage";
    badge.textContent = `+${whiteScore - blackScore}`;
    capturedByWhite.appendChild(badge);
  } else if (blackScore > whiteScore) {
    const badge = document.createElement("span");
    badge.className = "captured-advantage";
    badge.textContent = `+${blackScore - whiteScore}`;
    capturedByBlack.appendChild(badge);
  }
}

function sortByValue(kinds) {
  return [...kinds].sort((a, b) => (PIECE_VALUES[b] || 0) - (PIECE_VALUES[a] || 0));
}

function renderHighlights(state) {
  for (const tile of squaresLayer.children) {
    tile.classList.remove("selected", "legal", "capture");
    delete tile.dataset.lastMove;
    delete tile.dataset.check;
  }
  if (state.lastMove) {
    const f = squaresLayer.querySelector(`[data-square="${state.lastMove.from}"]`);
    const t = squaresLayer.querySelector(`[data-square="${state.lastMove.to}"]`);
    if (f) f.dataset.lastMove = "from";
    if (t) t.dataset.lastMove = "to";
  }
  if (state.inCheck && state.checkSquare) {
    const k = squaresLayer.querySelector(`[data-square="${state.checkSquare}"]`);
    if (k) k.dataset.check = "true";
  }
  if (selectedSquare) {
    const sel = squaresLayer.querySelector(`[data-square="${selectedSquare}"]`);
    if (sel) sel.classList.add("selected");
    for (const target of legalMoves) {
      const t = squaresLayer.querySelector(`[data-square="${target}"]`);
      if (!t) continue;
      const occupied = state.board[target] != null;
      t.classList.add(occupied ? "capture" : "legal");
    }
  }
}

function renderEndgame(state) {
  if (state.status === "active") { endgameSeen = false; return; }
  if (endgameSeen) return;
  endgameSeen = true;
  if (state.status === "checkmate") {
    endgameTitle.textContent = "Sah-mat!";
    endgameIcon.textContent = "\u265A";
    const winner = state.winnerLabel || (state.winner === "white" ? "Albe" : "Negre");
    endgameText.textContent = `${winner} castiga partida.`;
  } else if (state.status === "stalemate") {
    endgameTitle.textContent = "Pat";
    endgameIcon.textContent = "\u00BD";
    endgameText.textContent = "Partida se termina la egalitate.";
  } else if (state.status === "draw_insufficient") {
    endgameTitle.textContent = "Remiza";
    endgameIcon.textContent = "\u00BD";
    endgameText.textContent = "Material insuficient — nimeni nu poate da mat.";
  } else if (state.status === "draw_fifty_move") {
    endgameTitle.textContent = "Remiza";
    endgameIcon.textContent = "\u00BD";
    endgameText.textContent = "50 de mutari fara captura sau pion mutat.";
  } else if (state.status === "draw_repetition") {
    endgameTitle.textContent = "Remiza";
    endgameIcon.textContent = "\u00BD";
    endgameText.textContent = "Aceeasi pozitie a aparut de trei ori.";
  } else {
    endgameTitle.textContent = "Final";
    endgameIcon.textContent = "\u00BD";
    endgameText.textContent = "Partida s-a terminat.";
  }
  endgameModal.hidden = false;
}

function renderUndoButton(state) {
  undoButton.disabled = !state.canUndo;
}

function renderModeButton(state) {
  const session = state.session || {};
  if (session.mode === "vs_bot") {
    const human = session.botColor === "white" ? "Negre" : "Albe";
    modeButtonLabel.textContent = `vs Bot (${human})`;
  } else {
    modeButtonLabel.textContent = "1v1 Local";
  }
}

// ----- Main rendering pipeline -----

function applyState(newState) {
  const noPriorState = lastState === null;
  const oldHist = lastState ? lastState.history : [];
  const newHist = newState.history || [];

  if (noPriorState || newHist.length < oldHist.length) {
    rebuildAllPieces(newState.board);
  } else if (newHist.length > oldHist.length) {
    let projected = lastState ? { ...lastState.board } : {};
    for (let i = oldHist.length; i < newHist.length; i++) {
      const record = newHist[i];
      applyHistoryRecord(record, projected);
      projected = projectBoard(projected, record);
    }
  } else {
    if (JSON.stringify(boardKeyMap(newState.board)) !== JSON.stringify(boardKeyMap(lastState.board))) {
      rebuildAllPieces(newState.board);
    }
  }

  lastState = newState;
  renderStatus(newState);
  renderMoves(newState);
  renderCaptured(newState);
  renderHighlights(newState);
  renderUndoButton(newState);
  renderModeButton(newState);
  renderEndgame(newState);

  // If we're in vs-bot mode and it's the bot's turn, kick the bot.
  scheduleBotMoveIfNeeded(newState);
}

function boardKeyMap(board) {
  const out = {};
  for (const [sq, p] of Object.entries(board)) out[sq] = `${p.color}-${p.kind}`;
  return out;
}

function isBotsTurn(state) {
  const session = state && state.session;
  return (
    session &&
    session.mode === "vs_bot" &&
    session.botColor === state.turn &&
    state.status === "active"
  );
}

// ----- Bot move scheduling -----

async function scheduleBotMoveIfNeeded(state) {
  if (botPending) return;
  if (!isBotsTurn(state)) return;

  botPending = true;
  showBotThinking(true);
  // Small delay so the previous animation finishes and the indicator is visible.
  await sleep(200);

  try {
    const response = await fetch("/api/bot_move", { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Botul a esuat.");
    }
    setMessage("");
    applyState(data.state);
  } catch (err) {
    setMessage("Bot: " + err.message);
  } finally {
    showBotThinking(false);
    botPending = false;
  }
}

function showBotThinking(visible) {
  botThinking.hidden = !visible;
  if (visible) {
    boardEl.classList.add("waiting-for-bot");
  } else {
    boardEl.classList.remove("waiting-for-bot");
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ----- Interaction -----

async function handleSquareClick(square) {
  if (interactionLocked || pendingPromotion || botPending) return;
  const state = lastState;
  if (!state || state.status !== "active") return;
  // Don't let the human move bot pieces.
  if (isBotsTurn(state)) return;

  const piece = state.board[square];

  if (selectedSquare && legalMoves.includes(square)) {
    const movingPiece = state.board[selectedSquare];
    if (movingPiece && movingPiece.kind === "pawn") {
      const targetRank = Number(square[1]);
      if ((movingPiece.color === "white" && targetRank === 8) ||
          (movingPiece.color === "black" && targetRank === 1)) {
        openPromotionModal(selectedSquare, square, movingPiece.color);
        return;
      }
    }
    await submitMove(selectedSquare, square);
    return;
  }

  if (piece && piece.color === state.turn) {
    await selectSquare(square);
    return;
  }

  if (selectedSquare) {
    selectedSquare = null;
    legalMoves = [];
    renderHighlights(state);
  }

  if (piece && piece.color !== state.turn) {
    setMessage(`Este randul pieselor ${state.turnLabel.toLowerCase()}.`, "info");
  } else {
    setMessage("");
  }
}

async function selectSquare(square) {
  try {
    const response = await fetch(`/api/moves?from=${encodeURIComponent(square)}`);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Nu pot incarca mutarile.");
    selectedSquare = square;
    legalMoves = data.moves;
    setMessage("");
    lastState = data.state;
    renderHighlights(data.state);
  } catch (err) {
    selectedSquare = null;
    legalMoves = [];
    setMessage(err.message);
  }
}

async function submitMove(origin, target, promotion) {
  interactionLocked = true;
  try {
    const body = { from: origin, to: target };
    if (promotion) body.promotion = promotion;
    const response = await fetch("/api/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Mutarea a fost respinsa.");
    selectedSquare = null;
    legalMoves = [];
    setMessage("");
    applyState(data.state);
  } catch (err) {
    setMessage(err.message);
  } finally {
    setTimeout(() => { interactionLocked = false; }, 280);
  }
}

async function performUndo() {
  if (interactionLocked || botPending) return;
  if (!lastState || !lastState.canUndo) return;
  interactionLocked = true;
  try {
    const response = await fetch("/api/undo", { method: "POST" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Undo a esuat.");
    selectedSquare = null;
    legalMoves = [];
    setMessage("Ultima mutare a fost anulata.", "info");
    endgameModal.hidden = true;
    endgameSeen = false;
    applyState(data.state);
  } catch (err) {
    setMessage(err.message);
  } finally {
    setTimeout(() => { interactionLocked = false; }, 200);
  }
}

async function performReset() {
  if (interactionLocked) return;
  // If we're mid-bot-move, just cancel pending state.
  if (botPending) return;
  interactionLocked = true;
  try {
    const response = await fetch("/api/reset", { method: "POST" });
    const data = await response.json();
    selectedSquare = null;
    legalMoves = [];
    setMessage("");
    endgameModal.hidden = true;
    endgameSeen = false;
    lastState = null;
    applyState(data.state);
  } finally {
    setTimeout(() => { interactionLocked = false; }, 200);
  }
}

function performFlip() {
  isFlipped = !isFlipped;
  rebuildSquaresLayout();
  rebuildCoords();
  for (const id of Object.keys(pieceById)) {
    setPieceTransform(pieceById[id].element, pieceById[id].square, true);
  }
  if (lastState) {
    renderHighlights(lastState);
    renderStatus(lastState);
  }
}

// ----- Promotion modal -----

function openPromotionModal(from, to, color) {
  pendingPromotion = { from, to };
  promoChoices.innerHTML = "";
  for (const kind of ["queen", "rook", "bishop", "knight"]) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = color;
    btn.textContent = PIECE_SYMBOLS[color][kind];
    btn.title = kind;
    btn.addEventListener("click", () => choosePromotion(kind));
    promoChoices.appendChild(btn);
  }
  promoModal.hidden = false;
}

async function choosePromotion(kind) {
  const promo = pendingPromotion;
  pendingPromotion = null;
  promoModal.hidden = true;
  if (!promo) return;
  await submitMove(promo.from, promo.to, kind);
}

// ----- Mode selection modal -----

function openModeModal({ allowCancel = false } = {}) {
  // Pre-fill draft from current session if available.
  const session = lastState && lastState.session;
  if (session) {
    modeDraft.mode = session.mode || "local";
    if (session.botColor) {
      // Human plays the opposite color of the bot.
      modeDraft.color = session.botColor === "white" ? "black" : "white";
    }
  }
  modeCancel.hidden = !allowCancel;
  syncModeUI();
  modeModal.hidden = false;
}

function closeModeModal() {
  modeModal.hidden = true;
}

function syncModeUI() {
  for (const tile of modeChoicesWrap.querySelectorAll(".mode-tile")) {
    tile.classList.toggle("selected", tile.dataset.mode === modeDraft.mode);
  }
  modeOptions.hidden = modeDraft.mode !== "vs_bot";

  for (const pill of colorChoicesWrap.querySelectorAll(".pill")) {
    pill.classList.toggle("selected", pill.dataset.color === modeDraft.color);
  }
}

async function startSelectedMode() {
  const body = { mode: modeDraft.mode };
  if (modeDraft.mode === "vs_bot") {
    let humanColor = modeDraft.color;
    if (humanColor === "random") {
      humanColor = Math.random() < 0.5 ? "white" : "black";
    }
    body.botColor = humanColor === "white" ? "black" : "white";
    // If user is playing black, auto-flip so their pieces are on the bottom.
    if (humanColor === "black" && !isFlipped) {
      isFlipped = true;
      rebuildSquaresLayout();
      rebuildCoords();
    } else if (humanColor === "white" && isFlipped) {
      isFlipped = false;
      rebuildSquaresLayout();
      rebuildCoords();
    }
  } else {
    // Local mode: reset to white-at-bottom by default.
    if (isFlipped) {
      isFlipped = false;
      rebuildSquaresLayout();
      rebuildCoords();
    }
  }

  closeModeModal();

  try {
    const response = await fetch("/api/new_game", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Nu pot porni jocul.");
    selectedSquare = null;
    legalMoves = [];
    setMessage("");
    endgameModal.hidden = true;
    endgameSeen = false;
    lastState = null;
    applyState(data.state);
  } catch (err) {
    setMessage("Mod: " + err.message);
  }
}

// Wire up mode-modal interactions
modeChoicesWrap.addEventListener("click", (event) => {
  const tile = event.target.closest(".mode-tile");
  if (!tile) return;
  modeDraft.mode = tile.dataset.mode;
  syncModeUI();
});
colorChoicesWrap.addEventListener("click", (event) => {
  const pill = event.target.closest(".pill");
  if (!pill) return;
  modeDraft.color = pill.dataset.color;
  syncModeUI();
});
modeStart.addEventListener("click", startSelectedMode);
modeCancel.addEventListener("click", closeModeModal);
modeButton.addEventListener("click", () => openModeModal({ allowCancel: true }));

// ----- Auth -----

const TOKEN_KEY = 'chessmate_token';
let authToken = localStorage.getItem(TOKEN_KEY);
let currentUser = null;

const authModalEl    = document.querySelector('#auth-modal');
const authTabLogin   = document.querySelector('#auth-tab-login');
const authTabReg     = document.querySelector('#auth-tab-register');
const authLoginForm  = document.querySelector('#auth-login-form');
const authRegForm    = document.querySelector('#auth-register-form');
const authErrorEl    = document.querySelector('#auth-error');
const loginUserEl    = document.querySelector('#login-username');
const loginPassEl    = document.querySelector('#login-password');
const loginSubmitEl  = document.querySelector('#login-submit');
const regUserEl      = document.querySelector('#register-username');
const regPassEl      = document.querySelector('#register-password');
const regSubmitEl    = document.querySelector('#register-submit');
const userChipEl     = document.querySelector('#user-chip');
const userNameEl     = document.querySelector('#user-name');
const userRatingEl   = document.querySelector('#user-rating');
const logoutBtn      = document.querySelector('#logout-button');

function switchAuthTab(tab) {
  const isLogin = tab === 'login';
  authTabLogin.classList.toggle('active', isLogin);
  authTabReg.classList.toggle('active', !isLogin);
  authLoginForm.hidden = !isLogin;
  authRegForm.hidden = isLogin;
  authErrorEl.textContent = '';
}

function showAuthModal() {
  authErrorEl.textContent = '';
  authModalEl.hidden = false;
}

function hideAuthModal() {
  authModalEl.hidden = true;
}

function updateUserChip() {
  if (!currentUser) {
    userChipEl.hidden = true;
    logoutBtn.hidden = true;
    return;
  }
  userChipEl.hidden = false;
  logoutBtn.hidden = false;
  userNameEl.textContent = currentUser.username;
  userRatingEl.textContent = currentUser.rating ? `★ ${currentUser.rating}` : '';
}

async function performLogin(e) {
  e.preventDefault();
  const username = loginUserEl.value.trim();
  const password = loginPassEl.value;
  if (!username || !password) {
    authErrorEl.textContent = 'Completeaza toate câmpurile.';
    return;
  }
  loginSubmitEl.disabled = true;
  authErrorEl.textContent = '';
  try {
    const res  = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'Autentificare eșuată.');
    authToken = data.token;
    localStorage.setItem(TOKEN_KEY, authToken);
    currentUser = { username: data.username };
    hideAuthModal();
    updateUserChip();
    await loadInitialState();
  } catch (err) {
    authErrorEl.textContent = err.message;
  } finally {
    loginSubmitEl.disabled = false;
  }
}

async function performRegister(e) {
  e.preventDefault();
  const username = regUserEl.value.trim();
  const password = regPassEl.value;
  if (!username || !password) {
    authErrorEl.textContent = 'Completeaza toate câmpurile.';
    return;
  }
  regSubmitEl.disabled = true;
  authErrorEl.textContent = '';
  try {
    // Register
    const regRes  = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const regData = await regRes.json();
    if (!regData.ok) throw new Error(regData.error || 'Înregistrare eșuată.');
    // Auto-login after register
    const loginRes  = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const loginData = await loginRes.json();
    if (!loginData.ok) throw new Error('Cont creat! Conectează-te manual.');
    authToken = loginData.token;
    localStorage.setItem(TOKEN_KEY, authToken);
    currentUser = { username: loginData.username };
    hideAuthModal();
    updateUserChip();
    await loadInitialState();
  } catch (err) {
    authErrorEl.textContent = err.message;
  } finally {
    regSubmitEl.disabled = false;
  }
}

function performLogout() {
  authToken = null;
  currentUser = null;
  localStorage.removeItem(TOKEN_KEY);
  updateUserChip();
  loginUserEl.value = '';
  loginPassEl.value = '';
  regUserEl.value = '';
  regPassEl.value = '';
  switchAuthTab('login');
  showAuthModal();
}

async function checkAuthAndLoad() {
  if (!authToken) {
    showAuthModal();
    return;
  }
  try {
    const res  = await fetch('/auth/me', {
      headers: { 'Authorization': `Bearer ${authToken}` },
    });
    const data = await res.json();
    if (!data.ok) throw new Error('Token invalid');
    currentUser = { username: data.user.username, rating: data.user.rating };
    hideAuthModal();
    updateUserChip();
    await loadInitialState();
  } catch {
    authToken = null;
    localStorage.removeItem(TOKEN_KEY);
    showAuthModal();
  }
}

// Wire auth events
authTabLogin.addEventListener('click', () => switchAuthTab('login'));
authTabReg.addEventListener('click', () => switchAuthTab('register'));
authLoginForm.addEventListener('submit', performLogin);
authRegForm.addEventListener('submit', performRegister);
logoutBtn.addEventListener('click', performLogout);

// ----- Initial load -----

async function loadInitialState() {
  buildBoardScaffold();
  try {
    const response = await fetch("/api/state");
    const state = await response.json();
    applyState(state);
    // Always show the mode selector on first load so the user picks.
    // No "Back" — first load must end with a chosen mode.
    openModeModal({ allowCancel: false });
  } catch (err) {
    setMessage("Nu pot incarca starea: " + err.message);
  }
}

// ----- Wire up topbar -----

undoButton.addEventListener("click", performUndo);
flipButton.addEventListener("click", performFlip);
resetButton.addEventListener("click", performReset);
endgameClose.addEventListener("click", () => { endgameModal.hidden = true; });
endgameReset.addEventListener("click", () => { endgameModal.hidden = true; performReset(); });

checkAuthAndLoad();
