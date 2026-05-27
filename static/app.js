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
let mpSocket = null;
let mpStatus = "idle";          // idle | queue | active
let mpInfo = null;              // { roomId, color, opponent, timeControl }
let mpClock = null;             // { white, black, active }
let mpConfig = null;
let mpAuthPromise = null;
let mpAuthResolve = null;
let mpPendingMoves = null;
let mpQueueSince = null;
let mpQueueTimer = null;
// Mode-select draft state (mirrors UI selection inside the modal)
let modeDraft = { mode: "local", color: "white", minutes: 3, level: 3 };

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
// Puzzle DOM
const puzzleInfoEl = document.querySelector("#puzzle-info");
const puzzleRatingEl = document.querySelector("#puzzle-rating");
const puzzleProgressEl = document.querySelector("#puzzle-progress");
const puzzleThemesEl = document.querySelector("#puzzle-themes");
const puzzleFeedbackEl = document.querySelector("#puzzle-feedback");
const puzzleFeedbackTextEl = document.querySelector("#puzzle-feedback-text");
const puzzleHintBtn = document.querySelector("#puzzle-hint-btn");
const puzzleRandomBtn = document.querySelector("#puzzle-random-btn");
const puzzleThemeBtn = document.querySelector("#puzzle-theme-btn");
const puzzleSolvedModal = document.querySelector("#puzzle-solved-modal");
const puzzleSolvedText = document.querySelector("#puzzle-solved-text");
const puzzleSolvedClose = document.querySelector("#puzzle-solved-close");
const puzzleSolvedNext = document.querySelector("#puzzle-solved-next");
const puzzleThemeModal = document.querySelector("#puzzle-theme-modal");
const puzzleThemePickerSearch = document.querySelector("#puzzle-theme-picker-search");
const puzzleThemeCancel = document.querySelector("#puzzle-theme-cancel");
const puzzleThemeStart = document.querySelector("#puzzle-theme-start");
const puzzleOptionsEl = document.querySelector("#puzzle-options");
const puzzleThemeSearch = document.querySelector("#puzzle-theme-search"); // in mode modal
const themeDatalistModal = document.querySelector("#theme-datalist-modal");
const themeDatalistPicker = document.querySelector("#theme-datalist-picker");
const titleWhiteEl = document.querySelector("#title-white");
const titleBlackEl = document.querySelector("#title-black");
// Multiplayer DOM
const multiplayerOptionsEl = document.querySelector("#multiplayer-options");
const timeChoicesWrap = document.querySelector("#time-choices");
const mpOverlay = document.querySelector("#multiplayer-overlay");
const mpOverlayText = document.querySelector("#multiplayer-text");
const mpOverlayWait = document.querySelector("#multiplayer-wait");
const mpOverlayCancel = document.querySelector("#multiplayer-cancel");
const clockTop = document.querySelector("#clock-top");
const clockBottom = document.querySelector("#clock-bottom");

// ----- Helpers -----

function setMessage(text, kind = "error") {
  messageEl.textContent = text || "";
  messageEl.className = "message" + (text ? " " + kind : "");
}

function isMultiplayerMode(state) {
  return state && state.session && state.session.mode === "multiplayer";
}

function isMultiplayerPlayersTurn(state) {
  return isMultiplayerMode(state) && mpInfo && state.turn === mpInfo.color;
}

function formatClock(totalSec) {
  if (typeof totalSec !== "number") return "";
  const safe = Math.max(0, totalSec);
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function renderMultiplayerClock(state) {
  if (!clockTop || !clockBottom) return;
  if (!state || !isMultiplayerMode(state) || !mpClock) {
    clockTop.textContent = "";
    clockBottom.textContent = "";
    return;
  }
  const whiteTime = formatClock(mpClock.white);
  const blackTime = formatClock(mpClock.black);
  if (isFlipped) {
    clockTop.textContent = whiteTime;
    clockBottom.textContent = blackTime;
  } else {
    clockTop.textContent = blackTime;
    clockBottom.textContent = whiteTime;
  }
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

function resolvePlayerNames(state) {
  const session = state && state.session ? state.session : {};
  if (session.mode === "multiplayer") {
    const selfName = currentUser && currentUser.username ? currentUser.username : "Tu";
    if (mpInfo) {
      const oppName = mpInfo.opponent && mpInfo.opponent.username ? mpInfo.opponent.username : "Adversar";
      const whiteName = mpInfo.color === "white" ? selfName : oppName;
      const blackName = mpInfo.color === "black" ? selfName : oppName;
      return { whiteName, blackName };
    }
    return { whiteName: selfName, blackName: "Adversar" };
  }

  const botColor = session.mode === "vs_bot" ? session.botColor : null;
  const whiteName = botColor === "white" ? "BOT" : "PESSI";
  const blackName = botColor === "black" ? "BOT" : "RONALDO";
  return { whiteName, blackName };
}

function renderStatus(state) {
  const colorEn = state.turn === "white" ? "White" : "Black";
  turnText.textContent = state.status === "active" ? `${colorEn} to move` : labelForStatus(state);
  turnPill.dataset.turn = state.turn;
  const whiteCard = isFlipped ? playerTopCard : playerBottomCard;
  const blackCard = isFlipped ? playerBottomCard : playerTopCard;
  whiteCard.classList.toggle("active", state.turn === "white" && state.status === "active");
  blackCard.classList.toggle("active", state.turn === "black" && state.status === "active");

  // Swap player labels by current orientation. In vs-bot mode replace the
  // bot's display name so it's clear which side the engine controls.
  const { whiteName, blackName } = resolvePlayerNames(state);
  const topName  = playerTopCard.querySelector(".player-name");
  const topColor = playerTopCard.querySelector(".player-color");
  const topDot   = playerTopCard.querySelector(".player-dot");
  const botName  = playerBottomCard.querySelector(".player-name");
  const botColorEl = playerBottomCard.querySelector(".player-color");
  const botDot   = playerBottomCard.querySelector(".player-dot");
  if (isFlipped) {
    topName.textContent = whiteName;  topColor.textContent = "White";  topDot.className = "player-dot white";
    botName.textContent = blackName;  botColorEl.textContent = "Black"; botDot.className = "player-dot black";
  } else {
    topName.textContent = blackName;  topColor.textContent = "Black"; topDot.className = "player-dot black";
    botName.textContent = whiteName;  botColorEl.textContent = "White";  botDot.className = "player-dot white";
  }
  if (titleWhiteEl) titleWhiteEl.textContent = whiteName;
  if (titleBlackEl) titleBlackEl.textContent = blackName;
  renderMultiplayerClock(state);
}

function labelForStatus(state) {
  if (state.status === "checkmate") {
    const winner = state.winner === "white" ? "White" : "Black";
    return `Checkmate — ${winner} wins`;
  }
  if (state.status === "stalemate")          return "Stalemate — draw";
  if (state.status === "draw_insufficient")  return "Draw — insufficient material";
  if (state.status === "draw_fifty_move")    return "Draw — 50-move rule";
  if (state.status === "draw_repetition")    return "Draw — threefold repetition";
  if (state.status === "timeout")            return "Time out";
  if (state.status === "resign")             return "Resignation";
  if (state.status === "abandoned")          return "Game abandoned";
  return state.turn === "white" ? "White to move" : "Black to move";
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
    endgameTitle.textContent = "Checkmate";
    endgameIcon.textContent = "\u265A";
    const winner = state.winner === "white" ? "White" : "Black";
    endgameText.textContent = `${winner} wins.`;
  } else if (state.status === "stalemate") {
    endgameTitle.textContent = "Stalemate";
    endgameIcon.textContent = "\u00BD";
    endgameText.textContent = "Draw.";
  } else if (state.status === "draw_insufficient") {
    endgameTitle.textContent = "Draw";
    endgameIcon.textContent = "\u00BD";
    endgameText.textContent = "Insufficient material.";
  } else if (state.status === "draw_fifty_move") {
    endgameTitle.textContent = "Draw";
    endgameIcon.textContent = "\u00BD";
    endgameText.textContent = "50-move rule.";
  } else if (state.status === "draw_repetition") {
    endgameTitle.textContent = "Draw";
    endgameIcon.textContent = "\u00BD";
    endgameText.textContent = "Threefold repetition.";
  } else if (state.status === "timeout") {
    endgameTitle.textContent = "Time out";
    endgameIcon.textContent = "\u23F1";
    const winner = state.winner === "white" ? "White" : "Black";
    endgameText.textContent = `${winner} wins on time.`;
  } else if (state.status === "resign") {
    endgameTitle.textContent = "Resignation";
    endgameIcon.textContent = "\u2691";
    const winner = state.winner === "white" ? "White" : "Black";
    endgameText.textContent = `${winner} wins by resignation.`;
  } else if (state.status === "abandoned") {
    endgameTitle.textContent = "Game abandoned";
    endgameIcon.textContent = "\u2691";
    const winner = state.winner === "white" ? "White" : "Black";
    endgameText.textContent = `${winner} wins (opponent left).`;
  } else {
    endgameTitle.textContent = "Game over";
    endgameIcon.textContent = "\u00BD";
    endgameText.textContent = "";
  }
  endgameModal.hidden = false;
}

function renderUndoButton(state) {
  undoButton.disabled = isMultiplayerMode(state) || !state.canUndo;
}

function renderModeButton(state) {
  const session = state.session || {};
  if (session.mode === "multiplayer") {
    const base = (mpInfo && mpInfo.timeControl && mpInfo.timeControl.baseMin) || modeDraft.minutes || 3;
    modeButtonLabel.textContent = `Online ${base}+2`;
  } else if (session.mode === "vs_bot") {
    const human = session.botColor === "white" ? "Black" : "White";
    modeButtonLabel.textContent = `vs Bot (${human})`;
  } else if (session.mode === "puzzle") {
    modeButtonLabel.textContent = "Puzzle";
  } else {
    modeButtonLabel.textContent = "1v1 Local";
  }
}

function renderPuzzleInfo(state) {
  const inPuzzle = isPuzzleMode(state);
  puzzleInfoEl.hidden = !inPuzzle;
  if (!inPuzzle) return;

  const puzzle = state.puzzle || {};
  const colorLabel = puzzle.solverColor === "white" ? "White" : "Black";

  puzzleRatingEl.textContent = `★ ${puzzle.rating || "?"}`;
  puzzleProgressEl.textContent = puzzle.isComplete
    ? "Solved!"
    : `${puzzle.completedSteps}/${puzzle.totalSteps} moves (${colorLabel})`;

  puzzleThemesEl.innerHTML = "";
  for (const theme of (puzzle.themes || []).slice(0, 5)) {
    const tag = document.createElement("span");
    tag.className = "puzzle-theme-tag";
    tag.textContent = theme;
    puzzleThemesEl.appendChild(tag);
  }
}

function triggerBoardFlash(kind) {
  boardEl.classList.remove("flash-wrong", "flash-correct");
  void boardEl.offsetWidth; // reflow
  boardEl.classList.add(kind === "wrong" ? "flash-wrong" : "flash-correct");
  setTimeout(() => boardEl.classList.remove("flash-wrong", "flash-correct"), 600);
}

function showPuzzleSolvedModal(state) {
  const puzzle = state && state.puzzle;
  puzzleSolvedText.textContent = puzzle && puzzle.rating
    ? `Felicitări! Ai rezolvat un puzzle de rating ${puzzle.rating}.`
    : "Nice work - you found every correct move.";
  puzzleSolvedModal.hidden = false;
}

async function loadPuzzle(theme) {
  try {
    const body = theme ? { theme } : {};
    const response = await fetch("/api/puzzle/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "Nu pot încărca puzzle-ul.");
    setMessage("");
    endgameModal.hidden = true;
    endgameSeen = false;
    puzzleSolvedModal.hidden = true;
    lastState = null;
    // Auto-flip: solver with black pieces at bottom
    const solverColor = data.state?.puzzle?.solverColor;
    if (solverColor === "black" && !isFlipped) {
      isFlipped = true;
      rebuildSquaresLayout();
      rebuildCoords();
    } else if (solverColor === "white" && isFlipped) {
      isFlipped = false;
      rebuildSquaresLayout();
      rebuildCoords();
    }
    applyState(data.state);
    showPuzzleFeedback("Ce idee ai?", "hint");
  } catch (err) {
    setMessage("Puzzle: " + err.message);
  }
}

let _puzzleFeedbackTimer = null;

function showPuzzleFeedback(message, kind = "hint") {
  if (!puzzleFeedbackEl) return;
  if (puzzleFeedbackTextEl) puzzleFeedbackTextEl.textContent = message;
  puzzleFeedbackEl.dataset.kind = kind;
  // Force animation re-trigger so color change is visually immediate
  puzzleFeedbackEl.style.animation = "none";
  void puzzleFeedbackEl.offsetWidth;
  puzzleFeedbackEl.style.animation = "";
  puzzleFeedbackEl.hidden = false;
  clearTimeout(_puzzleFeedbackTimer);
  if (kind === "wrong") {
    // Revert to prompt after 3.5s
    _puzzleFeedbackTimer = setTimeout(() => showPuzzleFeedback("Ce idee ai?", "hint"), 3500);
  } else if (kind === "good") {
    // Revert to prompt after 1.5s
    _puzzleFeedbackTimer = setTimeout(() => showPuzzleFeedback("Ce idee ai?", "hint"), 1500);
  }
}

function hidePuzzleFeedback() {
  if (!puzzleFeedbackEl) return;
  puzzleFeedbackEl.hidden = true;
  clearTimeout(_puzzleFeedbackTimer);
}

async function loadPuzzleThemes(...datalistEls) {
  try {
    const response = await fetch("/api/puzzle/themes");
    const data = await response.json();
    if (!data.ok || !data.themes) return;
    for (const el of datalistEls) {
      if (!el) continue;
      el.innerHTML = "";
      for (const theme of data.themes) {
        const opt = document.createElement("option");
        opt.value = theme;
        el.appendChild(opt);
      }
    }
  } catch {
    // Puzzle DB unavailable — silently ignore
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
  renderPuzzleInfo(newState);

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

function isPuzzleMode(state) {
  return state && state.session && state.session.mode === "puzzle";
}

function isPuzzleOpponentTurn(state) {
  if (!isPuzzleMode(state)) return false;
  const puzzle = state.puzzle;
  if (!puzzle || puzzle.isComplete) return false;
  return state.turn !== puzzle.solverColor;
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
  if (isMultiplayerMode(state)) {
    if (mpStatus !== "active") return;
    if (!isMultiplayerPlayersTurn(state)) return;
  }
  // Don't let the human move bot pieces.
  if (isBotsTurn(state)) return;
  // In puzzle mode, only the solver can move and only when it's their turn.
  if (isPuzzleOpponentTurn(state)) return;
  if (isPuzzleMode(state) && state.puzzle && state.puzzle.isComplete) return;

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
  if (lastState && isMultiplayerMode(lastState)) {
    try {
      const data = await requestMultiplayerMoves(square);
      selectedSquare = square;
      legalMoves = data.moves || [];
      setMessage("");
      if (data.state) {
        applyState(data.state);
      } else if (lastState) {
        renderHighlights(lastState);
      }
    } catch (err) {
      selectedSquare = null;
      legalMoves = [];
      setMessage(err.message || "Nu pot incarca mutarile.");
    }
    return;
  }

  const endpoint = (lastState && isPuzzleMode(lastState))
    ? `/api/puzzle/moves?from=${encodeURIComponent(square)}`
    : `/api/moves?from=${encodeURIComponent(square)}`;
  try {
    const response = await fetch(endpoint);
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
  if (lastState && isMultiplayerMode(lastState)) {
    interactionLocked = true;
    try {
      await sendMultiplayerMove(origin, target, promotion);
      selectedSquare = null;
      legalMoves = [];
      setMessage("");
    } catch (err) {
      setMessage(err.message || "Move was rejected.");
    } finally {
      setTimeout(() => { interactionLocked = false; }, 200);
    }
    return;
  }

  interactionLocked = true;
  const inPuzzle = lastState && isPuzzleMode(lastState);
  const endpoint = inPuzzle ? "/api/puzzle/move" : "/api/move";
  try {
    const body = { from: origin, to: target };
    if (promotion) body.promotion = promotion;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();

    if (inPuzzle) {
      selectedSquare = null;
      legalMoves = [];
      if (!data.ok || data.correct === false) {
        triggerBoardFlash("wrong");
        showPuzzleFeedback("Wrong move - try again!", "wrong");
        if (data.state) applyState(data.state);
        return;
      }
      setMessage("");
      showPuzzleFeedback("Good move!", "good");
      applyState(data.state);
      if (data.complete) {
        showPuzzleSolvedModal(data.state);
      }
      return;
    }

    if (!response.ok || !data.ok) throw new Error(data.error || "Move was rejected.");
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
  if (lastState && isMultiplayerMode(lastState)) {
    setMessage("Undo nu este disponibil in multiplayer.", "info");
    return;
  }
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
  if (botPending) return;

  if (lastState && isMultiplayerMode(lastState)) {
    await leaveMultiplayer({ resign: true, resetSession: true });
    await loadLocalState({ openMode: true });
    return;
  }

  // In puzzle mode, "New game" loads a new random puzzle in the same theme
  if (lastState && isPuzzleMode(lastState)) {
    const theme = lastState?.puzzle?.themes?.[0] || null;
    await loadPuzzle(theme);
    return;
  }

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
    modeDraft.mode = session.mode === "puzzle" ? "puzzle" : (session.mode || "local");
    if (session.botColor) {
      // Human plays the opposite color of the bot.
      modeDraft.color = session.botColor === "white" ? "black" : "white";
    }
    if (session.mode === "multiplayer") {
      modeDraft.minutes =
        (session.timeControl && session.timeControl.baseMin)
        || (mpInfo && mpInfo.timeControl && mpInfo.timeControl.baseMin)
        || modeDraft.minutes;
    }
  }
  modeCancel.hidden = !allowCancel;
  syncModeUI();
  modeModal.hidden = false;

  // Populate puzzle theme datalists lazily
  if (themeDatalistModal && themeDatalistModal.options.length === 0) {
    loadPuzzleThemes(themeDatalistModal, themeDatalistPicker);
  }
}

function closeModeModal() {
  modeModal.hidden = true;
}

function syncModeUI() {
  for (const tile of modeChoicesWrap.querySelectorAll(".mode-tile")) {
    tile.classList.toggle("selected", tile.dataset.mode === modeDraft.mode);
  }
  modeOptions.hidden = modeDraft.mode !== "vs_bot";
  if (multiplayerOptionsEl) {
    multiplayerOptionsEl.hidden = modeDraft.mode !== "multiplayer";
  }
  puzzleOptionsEl.hidden = modeDraft.mode !== "puzzle";

  for (const pill of colorChoicesWrap.querySelectorAll(".pill")) {
    pill.classList.toggle("selected", pill.dataset.color === modeDraft.color);
  }
  // Bot level row + pills (only meaningful for vs_bot mode).
  const levelRow = document.querySelector("#level-row");
  const levelChoices = document.querySelector("#level-choices");
  if (levelRow) {
    levelRow.hidden = modeDraft.mode !== "vs_bot";
  }
  if (levelChoices) {
    for (const pill of levelChoices.querySelectorAll(".pill")) {
      pill.classList.toggle(
        "selected",
        Number(pill.dataset.level) === Number(modeDraft.level || 3)
      );
    }
  }
  if (timeChoicesWrap) {
    for (const pill of timeChoicesWrap.querySelectorAll(".pill")) {
      pill.classList.toggle(
        "selected",
        Number(pill.dataset.minutes) === Number(modeDraft.minutes)
      );
    }
  }
}

async function startSelectedMode() {
  if (lastState && isMultiplayerMode(lastState) && modeDraft.mode !== "multiplayer") {
    await leaveMultiplayer({ resign: true, silent: true });
  }

  if (modeDraft.mode === "puzzle") {
    closeModeModal();
    const theme = puzzleThemeSearch ? puzzleThemeSearch.value.trim() : "";
    await loadPuzzle(theme || null);
    return;
  }

  if (modeDraft.mode === "multiplayer") {
    closeModeModal();
    await startMultiplayer(modeDraft.minutes || 3);
    return;
  }

  const body = { mode: modeDraft.mode };
  if (modeDraft.mode === "vs_bot") {
    let humanColor = modeDraft.color;
    if (humanColor === "random") {
      humanColor = Math.random() < 0.5 ? "white" : "black";
    }
    body.botColor = humanColor === "white" ? "black" : "white";
    body.level = Number(modeDraft.level || 3);
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
if (timeChoicesWrap) {
  timeChoicesWrap.addEventListener("click", (event) => {
    const pill = event.target.closest(".pill");
    if (!pill) return;
    modeDraft.minutes = Number(pill.dataset.minutes) || 3;
    syncModeUI();
  });
}
const levelChoicesWrap = document.querySelector("#level-choices");
if (levelChoicesWrap) {
  levelChoicesWrap.addEventListener("click", (event) => {
    const pill = event.target.closest(".pill");
    if (!pill) return;
    modeDraft.level = Number(pill.dataset.level) || 3;
    syncModeUI();
  });
}
modeStart.addEventListener("click", startSelectedMode);
modeCancel.addEventListener("click", closeModeModal);
modeButton.addEventListener("click", () => openModeModal({ allowCancel: true }));

// ----- Multiplayer (WebSocket) -----

function decorateMultiplayerState(state) {
  if (!state) return state;
  const session = {
    mode: "multiplayer",
    roomId: mpInfo ? mpInfo.roomId : null,
    timeControl: mpInfo ? mpInfo.timeControl : null,
  };
  return { ...state, session, canUndo: false };
}

async function loadMultiplayerConfig() {
  if (mpConfig) return mpConfig;
  try {
    const response = await fetch("/api/mp_config");
    const data = await response.json();
    if (data && data.ok) {
      mpConfig = data;
      return data;
    }
  } catch {
    // ignore
  }
  mpConfig = { wsUrl: null, baseMinutes: [3, 5, 10], incrementSec: 2 };
  return mpConfig;
}

function deriveMultiplayerWsUrl() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.hostname;
  const port = "8000";
  return `${scheme}://${host}:${port}/ws`;
}

async function ensureMultiplayerSocket() {
  if (mpSocket && (mpSocket.readyState === WebSocket.OPEN || mpSocket.readyState === WebSocket.CONNECTING)) {
    return mpAuthPromise;
  }

  const config = await loadMultiplayerConfig();
  const wsUrl = config.wsUrl || deriveMultiplayerWsUrl();

  mpAuthPromise = new Promise((resolve) => {
    mpAuthResolve = resolve;
  });

  mpSocket = new WebSocket(wsUrl);
  mpSocket.addEventListener("open", () => {
    mpSocket.send(JSON.stringify({ type: "auth", token: authToken }));
  });
  mpSocket.addEventListener("message", handleMultiplayerMessage);
  mpSocket.addEventListener("close", () => {
    mpStatus = "idle";
    mpInfo = null;
    mpClock = null;
    showMultiplayerOverlay(false);
  });
  mpSocket.addEventListener("error", () => {
    setMessage("Multiplayer: conexiune esuata.");
  });

  return mpAuthPromise;
}

function showMultiplayerOverlay(visible, text) {
  if (!mpOverlay) return;
  mpOverlay.hidden = !visible;
  if (mpOverlayText && text) {
    mpOverlayText.textContent = text;
  }
  if (!visible) {
    stopQueueTimer();
  }
}

function startQueueTimer() {
  if (!mpOverlayWait) return;
  stopQueueTimer();
  mpQueueSince = Date.now();
  mpOverlayWait.textContent = "Wait time: 0:00";
  mpQueueTimer = setInterval(() => {
    if (!mpQueueSince) return;
    const elapsed = Math.max(0, Math.floor((Date.now() - mpQueueSince) / 1000));
    const minutes = Math.floor(elapsed / 60);
    const seconds = String(elapsed % 60).padStart(2, "0");
    mpOverlayWait.textContent = `Wait time: ${minutes}:${seconds}`;
  }, 1000);
}

function stopQueueTimer() {
  if (mpQueueTimer) {
    clearInterval(mpQueueTimer);
    mpQueueTimer = null;
  }
  mpQueueSince = null;
}

async function startMultiplayer(minutes) {
  if (!authToken) {
    showAuthModal();
    return;
  }

  if (mpStatus === "queue" || mpStatus === "active") {
    await leaveMultiplayer({ resign: mpStatus === "active", silent: true });
  }

  try {
    const response = await fetch("/api/new_game", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "multiplayer" }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "Nu pot porni multiplayer.");
    }
    if (data.state) {
      applyState(decorateMultiplayerState(data.state));
    }
  } catch (err) {
    setMessage(err.message || "Nu pot porni multiplayer.");
    return;
  }

  mpStatus = "queue";
  showMultiplayerOverlay(true, "Conectare la server...");

  await ensureMultiplayerSocket();
  try {
    await Promise.race([
      mpAuthPromise,
      new Promise((_, reject) => setTimeout(() => reject(new Error("Auth timeout")), 5000)),
    ]);
  } catch (err) {
    await leaveMultiplayer({ silent: true, resetSession: true });
    await loadLocalState({ openMode: true });
    setMessage("Multiplayer: autentificare esuata.");
    return;
  }

  showMultiplayerOverlay(true, "Looking for an opponent...");
  mpSocket.send(JSON.stringify({ type: "join_queue", minutes }));
}

async function leaveMultiplayer({ resign = false, silent = false, resetSession = false } = {}) {
  if (mpSocket && mpSocket.readyState === WebSocket.OPEN) {
    if (mpStatus === "queue") {
      mpSocket.send(JSON.stringify({ type: "cancel_queue" }));
    }
    if (mpStatus === "active" && resign) {
      mpSocket.send(JSON.stringify({ type: "resign" }));
    }
  }
  mpStatus = "idle";
  mpInfo = null;
  mpClock = null;
  mpPendingMoves = null;
  showMultiplayerOverlay(false);
  renderMultiplayerClock(lastState);
  if (resetSession) {
    try {
      await fetch("/api/new_game", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "local" }),
      });
    } catch {
      // ignore
    }
  }
  if (!silent) {
    setMessage("Ai iesit din multiplayer.", "info");
  }
}

function handleMultiplayerMessage(event) {
  let msg = null;
  try {
    msg = JSON.parse(event.data);
  } catch {
    return;
  }

  switch (msg.type) {
    case "auth_ok":
      if (mpAuthResolve) mpAuthResolve(msg.user);
      return;
    case "queued":
      mpStatus = "queue";
      showMultiplayerOverlay(true, "Looking for an opponent...");
      startQueueTimer();
      return;
    case "queue_canceled":
      mpStatus = "idle";
      showMultiplayerOverlay(false);
      stopQueueTimer();
      return;
    case "match_found":
      mpStatus = "active";
      mpInfo = {
        roomId: msg.roomId,
        color: msg.color,
        opponent: msg.opponent,
        timeControl: msg.timeControl,
      };
      mpClock = msg.clock || mpClock;
      showMultiplayerOverlay(false);
      stopQueueTimer();
      if (msg.state) {
        applyState(decorateMultiplayerState(msg.state));
      }
      return;
    case "reconnected":
      mpStatus = "active";
      mpInfo = {
        roomId: msg.roomId,
        color: msg.color,
        opponent: msg.opponent,
        timeControl: msg.timeControl || (mpInfo ? mpInfo.timeControl : null),
      };
      mpClock = msg.clock || mpClock;
      showMultiplayerOverlay(false);
      if (msg.state) {
        applyState(decorateMultiplayerState(msg.state));
      }
      return;
    case "state":
      if (msg.clock) mpClock = msg.clock;
      if (msg.state) {
        applyState(decorateMultiplayerState(msg.state));
      }
      return;
    case "clock":
      mpClock = msg.clock || mpClock;
      renderMultiplayerClock(lastState);
      return;
    case "moves":
      if (mpPendingMoves && mpPendingMoves.square === msg.from) {
        mpPendingMoves.resolve({ moves: msg.moves || [], state: decorateMultiplayerState(msg.state) });
        mpPendingMoves = null;
      }
      return;
    case "game_over":
      mpStatus = "idle";
      showMultiplayerOverlay(false);
      stopQueueTimer();
      if (msg.clock) mpClock = msg.clock;
      if (msg.state) {
        applyState(decorateMultiplayerState(msg.state));
      }
      return;
    case "opponent_left":
      setMessage("Adversarul s-a deconectat.", "info");
      return;
    case "opponent_back":
      setMessage("");
      return;
    case "error":
      setMessage(msg.message || "Eroare multiplayer.");
      interactionLocked = false;
      if (mpPendingMoves) {
        mpPendingMoves.reject(new Error(msg.message || "Eroare la mutari."));
        mpPendingMoves = null;
      }
      return;
    default:
      return;
  }
}

async function requestMultiplayerMoves(square) {
  if (!mpSocket || mpSocket.readyState !== WebSocket.OPEN) {
    throw new Error("Conexiune multiplayer indisponibila.");
  }
  if (mpPendingMoves) {
    throw new Error("Asteapta raspunsul anterior.");
  }
  return new Promise((resolve, reject) => {
    mpPendingMoves = { square, resolve, reject };
    mpSocket.send(JSON.stringify({ type: "moves", from: square }));
    setTimeout(() => {
      if (mpPendingMoves && mpPendingMoves.square === square) {
        mpPendingMoves = null;
        reject(new Error("Timeout la mutari."));
      }
    }, 3000);
  });
}

async function sendMultiplayerMove(origin, target, promotion) {
  if (!mpSocket || mpSocket.readyState !== WebSocket.OPEN) {
    throw new Error("Conexiune multiplayer indisponibila.");
  }
  mpSocket.send(JSON.stringify({
    type: "move",
    from: origin,
    to: target,
    promotion,
  }));
}

if (mpOverlayCancel) {
  mpOverlayCancel.addEventListener("click", async () => {
    await leaveMultiplayer({ resign: mpStatus === "active", resetSession: true });
    await loadLocalState({ openMode: true });
  });
}

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
    await performLoginAndContinue();
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
    if (!regData.ok) throw new Error(regData.error || 'Registration failed.');
    // Auto-login after register
    const loginRes  = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const loginData = await loginRes.json();
    if (!loginData.ok) throw new Error('Account created. Please log in.');
    authToken = loginData.token;
    localStorage.setItem(TOKEN_KEY, authToken);
    currentUser = { username: loginData.username };
    await performLoginAndContinue();
  } catch (err) {
    authErrorEl.textContent = err.message;
  } finally {
    regSubmitEl.disabled = false;
  }
}

function performLogout() {
  leaveMultiplayer({ resign: false, silent: true });
  if (mpSocket) {
    mpSocket.close();
    mpSocket = null;
  }
  authToken = null;
  currentUser = null;
  localStorage.removeItem(TOKEN_KEY);
  updateUserChip();
  loginUserEl.value = '';
  loginPassEl.value = '';
  regUserEl.value = '';
  regPassEl.value = '';
  switchAuthTab('login');
  // If we are on a protected mode, go home; otherwise stay (guests can keep playing).
  const mode = currentUrlMode();
  if (mode === 'multiplayer' || mode === 'puzzle') {
    location.href = '/';
  }
}

// Modal-close, login-shortcut and back-home flow are wired further down
// in the "Routing / boot" section.

async function performLoginAndContinue() {
  // After login, retry the requested mode from the URL.
  hideAuthModal();
  updateUserChip();
  await loadInitialState({ skipAutoStart: true });
  await loadMultiplayerConfig();
  await applyUrlModeAfterAuth();
}

async function checkAuthSilently() {
  if (!authToken) return false;
  try {
    const res  = await fetch('/auth/me', {
      headers: { 'Authorization': `Bearer ${authToken}` },
    });
    const data = await res.json();
    if (!data.ok) throw new Error('Token invalid');
    currentUser = { username: data.user.username, rating: data.user.rating };
    updateUserChip();
    return true;
  } catch {
    authToken = null;
    localStorage.removeItem(TOKEN_KEY);
    currentUser = null;
    updateUserChip();
    return false;
  }
}

// Wire auth events
authTabLogin.addEventListener('click', () => switchAuthTab('login'));
authTabReg.addEventListener('click', () => switchAuthTab('register'));
authLoginForm.addEventListener('submit', performLogin);
authRegForm.addEventListener('submit', performRegister);
logoutBtn.addEventListener('click', performLogout);

// ----- Initial load -----

async function loadInitialState({ skipAutoStart = false } = {}) {
  buildBoardScaffold();
  await loadLocalState({ openMode: !skipAutoStart, allowCancel: true });
}

async function loadLocalState({ openMode = false, allowCancel = true } = {}) {
  try {
    const response = await fetch("/api/state");
    const state = await response.json();
    applyState(state);
    if (openMode) {
      openModeModal({ allowCancel });
    }
  } catch (err) {
    setMessage("Cannot load state: " + err.message);
  }
}

// ----- Wire up topbar -----

undoButton.addEventListener("click", performUndo);
flipButton.addEventListener("click", performFlip);
resetButton.addEventListener("click", performReset);
endgameClose.addEventListener("click", () => { endgameModal.hidden = true; });
endgameReset.addEventListener("click", () => { endgameModal.hidden = true; performReset(); });

// ----- Puzzle controls -----

let _hintClearTimer = null;

async function showPuzzleHint() {
  try {
    const res = await fetch("/api/puzzle/hint");
    const data = await res.json();
    if (!data.ok) { setMessage(data.error || "No hint available.", "error"); return; }

    // Highlight the hint squares on the board
    clearTimeout(_hintClearTimer);
    selectedSquare = data.from;
    legalMoves = [data.to];
    if (lastState) renderHighlights(lastState);
    showPuzzleFeedback(`Move from ${data.from} to ${data.to}`, "hint");

    _hintClearTimer = setTimeout(() => {
      selectedSquare = null;
      legalMoves = [];
      if (lastState) renderHighlights(lastState);
    }, 4000);
  } catch (err) {
    setMessage("Hint: " + err.message);
  }
}

puzzleHintBtn.addEventListener("click", showPuzzleHint);
puzzleRandomBtn.addEventListener("click", () => loadPuzzle(null));

puzzleThemeBtn.addEventListener("click", () => {
  if (themeDatalistPicker && themeDatalistPicker.options.length === 0) {
    loadPuzzleThemes(themeDatalistModal, themeDatalistPicker);
  }
  puzzleThemeModal.hidden = false;
});
puzzleThemeCancel.addEventListener("click", () => {
  puzzleThemeModal.hidden = true;
});
puzzleThemeStart.addEventListener("click", () => {
  const theme = (puzzleThemePickerSearch ? puzzleThemePickerSearch.value.trim() : "") || null;
  puzzleThemeModal.hidden = true;
  if (puzzleThemePickerSearch) puzzleThemePickerSearch.value = "";
  loadPuzzle(theme);
});

puzzleSolvedClose.addEventListener("click", () => {
  puzzleSolvedModal.hidden = true;
});
puzzleSolvedNext.addEventListener("click", () => {
  puzzleSolvedModal.hidden = true;
  const theme = lastState?.puzzle?.themes?.[0] || null;
  loadPuzzle(theme);
});

// ============================================================
// Routing / boot
// Read the mode from the URL path and start the matching flow.
//   /play/bot      -> bot setup (guest OK)
//   /play/local    -> 1v1 same computer (guest OK)
//   /play/online   -> matchmaking (requires login)
//   /puzzles       -> puzzle (requires login)
//   /              -> we are on the home page, not here
// Anything else just opens the mode picker.
// ============================================================
function currentUrlMode() {
  const path = (location.pathname || '').replace(/\/$/, '');
  if (path === '/play/bot')    return 'vs_bot';
  if (path === '/play/local')  return 'local';
  if (path === '/play/online') return 'multiplayer';
  if (path === '/puzzles')     return 'puzzle';
  // Backwards compat for the older /bot path
  if (path === '/bot') return 'vs_bot';
  // Query fallback
  const q = new URLSearchParams(location.search).get('mode');
  if (q === 'bot')        return 'vs_bot';
  if (q === 'local')      return 'local';
  if (q === 'online')     return 'multiplayer';
  if (q === 'puzzle')     return 'puzzle';
  return null;
}

function modeRequiresAuth(mode) {
  return mode === 'multiplayer' || mode === 'puzzle';
}

function presetSetupDraftFromUrl() {
  const mode = currentUrlMode();
  if (!mode) return false;
  modeDraft.mode = mode;
  const params = new URLSearchParams(location.search);
  const color = params.get('color');
  if (color && ['white', 'black', 'random'].includes(color)) {
    modeDraft.color = color;
  }
  const level = params.get('level');
  if (level && ['1', '2', '3', '4'].includes(level)) {
    modeDraft.level = Number(level);
  }
  const minutes = params.get('minutes');
  if (minutes && ['3', '5', '10'].includes(minutes)) {
    modeDraft.minutes = Number(minutes);
  }
  return true;
}

async function applyUrlModeAfterAuth() {
  // Called after a successful login from the protected-mode flow.
  if (presetSetupDraftFromUrl()) {
    await startSelectedMode();
  }
}

// Login shortcut (in topbar, shown when guest)
const loginShortcutBtn = document.querySelector('#login-shortcut');
if (loginShortcutBtn) {
  loginShortcutBtn.addEventListener('click', () => {
    switchAuthTab('login');
    showAuthModal();
  });
}

// Auth-modal close button (only enabled when login isn't strictly required).
const authModalCloseBtn = document.querySelector('#auth-modal-close');
if (authModalCloseBtn) {
  authModalCloseBtn.addEventListener('click', () => {
    hideAuthModal();
    // If the user dismissed a forced login on a protected mode, go home.
    if (modeRequiresAuth(currentUrlMode())) location.href = '/';
  });
}

// Reveal/hide the topbar auth buttons based on currentUser.
const profileLinkEl = document.querySelector('#profile-link');
function refreshTopbarAuthButtons() {
  const isAuthed = !!currentUser;
  if (loginShortcutBtn) loginShortcutBtn.hidden = isAuthed;
  if (profileLinkEl)    profileLinkEl.hidden    = !isAuthed;
  if (logoutBtn)        logoutBtn.hidden        = !isAuthed;
}
const _origUpdateUserChip = updateUserChip;
updateUserChip = function patchedUpdateUserChip() {
  _origUpdateUserChip();
  refreshTopbarAuthButtons();
};

// ============================================================
// Side panel: bot/online "game info" card replaces the puzzle card
// in non-puzzle modes. Driven from applyState via patched render.
// ============================================================
const gameInfoCard    = document.querySelector('#game-info-card');
const gameInfoBot     = document.querySelector('#info-bot-level');
const gameInfoCol     = document.querySelector('#info-your-color');
const gameInfoLast    = document.querySelector('#info-last-bot');
const gameInfoLastRow = document.querySelector('#info-row-last');
const gameInfoBotRow  = document.querySelector('#info-row-bot');
const gameInfoStatus  = document.querySelector('#info-status');

const LEVEL_NAMES = ['', 'Beginner', 'Medium', 'Advanced', 'Expert'];

function renderGameInfoCard(state) {
  if (!gameInfoCard) return;
  const sess = state && state.session;
  const mode = sess && sess.mode;
  // Hide the bot/info card in puzzle mode (puzzle has its own card) or when
  // there is no session yet.
  if (!sess || mode === 'puzzle') {
    gameInfoCard.hidden = true;
    return;
  }
  gameInfoCard.hidden = false;

  if (mode === 'vs_bot') {
    gameInfoBotRow.hidden = false;
    gameInfoBot.textContent = LEVEL_NAMES[modeDraft.level || 3] || 'Advanced';
  } else {
    gameInfoBotRow.hidden = true;
  }

  let myColor = '—';
  if (mode === 'vs_bot')          myColor = sess.botColor === 'white' ? 'Black' : 'White';
  else if (mode === 'local')      myColor = 'Both';
  else if (mode === 'multiplayer' && state.yourColor) {
    myColor = state.yourColor === 'white' ? 'White' : 'Black';
  }
  gameInfoCol.textContent = myColor;

  if (mode === 'vs_bot') {
    const hist = state.history || [];
    const last = hist[hist.length - 1];
    if (last && last.san) {
      gameInfoLastRow.hidden = false;
      gameInfoLast.textContent = last.san;
    } else {
      gameInfoLastRow.hidden = true;
    }
  } else {
    gameInfoLastRow.hidden = true;
  }

  const statusMap = {
    active: state.turn === 'white' ? 'White to move' : 'Black to move',
    checkmate: 'Checkmate',
    stalemate: 'Stalemate',
    draw_insufficient: 'Draw',
    draw_fifty_move: 'Draw',
    draw_repetition: 'Draw',
    timeout: 'Time out',
    resign: 'Resignation',
    abandoned: 'Abandoned',
  };
  gameInfoStatus.textContent = statusMap[state.status] || state.status;
}

// Resign button — visible during active bot/online games only.
const resignBtnTop = document.querySelector('#resign-button');
function refreshResignBtn(state) {
  if (!resignBtnTop) return;
  const sess = state && state.session;
  const mode = sess && sess.mode;
  const inBotOrOnline = mode === 'vs_bot' || mode === 'multiplayer';
  resignBtnTop.hidden = !(state && state.status === 'active' && inBotOrOnline);
}
if (resignBtnTop) {
  resignBtnTop.addEventListener('click', async () => {
    if (!lastState || lastState.status !== 'active') return;
    const sess = lastState.session || {};
    if (sess.mode === 'multiplayer') {
      try { await leaveMultiplayer({ resign: true }); } catch (_) {}
      return;
    }
    // Bot resignation — legacy /api/* has no resign endpoint, so we apply it
    // locally so the end-game modal + record-on-end hooks fire correctly.
    const userColor = sess.botColor === 'white' ? 'black' : 'white';
    const winnerSide = userColor === 'white' ? 'black' : 'white';
    applyState(Object.assign({}, lastState, {
      status: 'resign',
      winner: winnerSide,
    }));
  });
}

// Patch renderModeButton (called from applyState) to also drive our new cards.
const _origRenderModeButton = renderModeButton;
renderModeButton = function patchedRenderModeButton(state) {
  _origRenderModeButton(state);
  renderGameInfoCard(state);
  refreshResignBtn(state);
};

// ============================================================
// Persist finished bot games to /games/history (auth required).
// ============================================================
let _lastRecordedKey = null;
async function maybeRecordBotGame(state) {
  if (!currentUser || !authToken) return;
  if (!state || state.status === 'active') return;
  const sess = state.session || {};
  if (sess.mode !== 'vs_bot') return;

  const hist = state.history || [];
  const moves = hist.map((h) => {
    let uci = (h.from || '') + (h.to || '');
    if (h.promotionKind) {
      uci += h.promotionKind[0]; // "queen" -> "q"
    } else if (h.promotion) {
      uci += String(h.promotion)[0];
    }
    return uci;
  }).filter((m) => m && m.length >= 4);

  const key = `${state.status}|${state.winner || ''}|${moves.length}|${moves.join('')}`;
  if (key === _lastRecordedKey) return;
  _lastRecordedKey = key;

  const userColor = sess.botColor === 'white' ? 'black' : 'white';
  const statusMap = {
    checkmate: state.winner ? `${state.winner}_win` : 'draw',
    stalemate: 'draw',
    draw_insufficient: 'draw',
    draw_fifty_move: 'draw',
    draw_repetition: 'draw',
    resign: state.winner ? `${state.winner}_win` : 'aborted',
    timeout: state.winner ? `${state.winner}_win` : 'aborted',
    abandoned: state.winner ? `${state.winner}_win` : 'aborted',
  };
  const reasonMap = {
    checkmate: 'checkmate',
    stalemate: 'stalemate',
    draw_insufficient: 'draw_insufficient',
    draw_fifty_move: 'draw_50_move',
    draw_repetition: 'draw_threefold',
    resign: 'resignation',
    timeout: 'timeout',
    abandoned: 'engine_error',
  };

  try {
    await fetch('/games/record', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${authToken}`,
      },
      body: JSON.stringify({
        color: userColor,
        bot_level: modeDraft.level || 3,
        status: statusMap[state.status] || 'aborted',
        result_reason: reasonMap[state.status] || null,
        moves,
        fen: state.fen || null,
      }),
    });
  } catch (_) { /* non-fatal */ }
}

async function boot() {
  buildBoardScaffold();

  // 1) Silent token check (never blocks guests).
  await checkAuthSilently();
  await loadMultiplayerConfig();

  const mode = currentUrlMode();

  // 2) Protected modes require login.
  if (modeRequiresAuth(mode) && !currentUser) {
    switchAuthTab('login');
    showAuthModal();
    await loadLocalState({ openMode: false });
    return;
  }

  // 3) Load state, then open the setup modal pre-filled. We never auto-start;
  //    the user clicks Start to begin so all entry points feel the same.
  await loadLocalState({ openMode: false });
  if (mode) {
    openModeModal({ allowCancel: false });
    presetSetupDraftFromUrl();
    syncModeUI();
  } else {
    openModeModal({ allowCancel: true });
  }
}

boot();
