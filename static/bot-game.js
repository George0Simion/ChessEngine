/* ============================================================
   ChessMate — Bot game page logic (bot-game.js)
   Connects to /games/* via GamesAPI (games-api.js).
   Board is rendered from FEN; moves submitted in UCI notation.
   ============================================================ */

// ----- Constants (same as main app) -----
const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];
const RANKS_TOP_DOWN = [8, 7, 6, 5, 4, 3, 2, 1];
const PIECE_SYMBOLS = {
  white: { king: "\u265A", queen: "\u265B", rook: "\u265C", bishop: "\u265D", knight: "\u265E", pawn: "\u265F" },
  black: { king: "\u265A", queen: "\u265B", rook: "\u265C", bishop: "\u265D", knight: "\u265E", pawn: "\u265F" },
};
const FEN_PIECE = {
  K: { color: "white", kind: "king" },   Q: { color: "white", kind: "queen" },
  R: { color: "white", kind: "rook" },   B: { color: "white", kind: "bishop" },
  N: { color: "white", kind: "knight" }, P: { color: "white", kind: "pawn" },
  k: { color: "black", kind: "king" },   q: { color: "black", kind: "queen" },
  r: { color: "black", kind: "rook" },   b: { color: "black", kind: "bishop" },
  n: { color: "black", kind: "knight" }, p: { color: "black", kind: "pawn" },
};

// ----- Game state -----
let gameId       = null;
let userColor    = null;   // "white" | "black"
let botLevel     = null;   // 1..4
let gameStatus   = "active";
let resultReason = null;
let moveHistory  = [];     // array of UCI strings, e.g. ["e2e4", "e7e5"]
let currentBoard = {};     // square -> { color, kind }
let sideToMove   = "white";

// ----- Board UI state -----
let isFlipped        = false;
let selectedSquare   = null;
let interactionLocked = false;
let pendingPromotion = null;
let endgameSeen      = false;

// ----- Piece DOM tracking -----
let pieceMap  = {};  // square -> pieceId
let pieceById = {};  // pieceId -> { square, color, kind, element }
let pieceIdSeq = 0;

// ----- DOM refs -----
const boardEl        = document.querySelector("#board");
const squaresLayer   = document.querySelector("#squares-layer");
const piecesLayer    = document.querySelector("#pieces-layer");
const coordsFiles    = document.querySelector("#coords-files");
const coordsRanks    = document.querySelector("#coords-ranks");
const messageEl      = document.querySelector("#message");
const turnPill       = document.querySelector("#turn-pill");
const turnText       = document.querySelector("#turn-text");
const moveCountBadge = document.querySelector("#move-count");
const movesList      = document.querySelector("#moves-list");
const movesEmpty     = document.querySelector("#moves-empty");
const botThinking    = document.querySelector("#bot-thinking");
const setupScreenEl  = document.querySelector("#setup-screen");
const gameScreenEl   = document.querySelector("#game-screen");
const startBtn       = document.querySelector("#start-button");
const newGameBtn     = document.querySelector("#new-game-button");
const resignBtn      = document.querySelector("#resign-button");
const flipBtn        = document.querySelector("#flip-button");
const setupErrorEl   = document.querySelector("#setup-error");
const authModalEl    = document.querySelector("#auth-modal");
const endgameModal   = document.querySelector("#endgame-modal");
const endgameTitle   = document.querySelector("#endgame-title");
const endgameText    = document.querySelector("#endgame-text");
const endgameIcon    = document.querySelector("#endgame-icon");
const endgameClose   = document.querySelector("#endgame-close");
const endgameNew     = document.querySelector("#endgame-new");
const promoModal     = document.querySelector("#promo-modal");
const promoChoices   = document.querySelector("#promo-choices");
const userChipEl     = document.querySelector("#user-chip");
const userNameEl     = document.querySelector("#user-name");
const topNameEl      = document.querySelector("#top-name");
const topColorEl     = document.querySelector("#top-color");
const topDotEl       = document.querySelector("#top-dot");
const topBadgeEl     = document.querySelector("#top-badge");
const bottomNameEl   = document.querySelector("#bottom-name");
const bottomColorEl  = document.querySelector("#bottom-color");
const bottomDotEl    = document.querySelector("#bottom-dot");
const bottomBadgeEl  = document.querySelector("#bottom-badge");
const infoLevel      = document.querySelector("#info-level");
const infoColor      = document.querySelector("#info-color");
const infoStatus     = document.querySelector("#info-status");
const infoReasonRow  = document.querySelector("#info-reason-row");
const infoReason     = document.querySelector("#info-reason");

// ----- Setup form draft -----
let setupDraft = { color: "white", level: 2 };

// ============================================================
// FEN parser — produces board dict + sideToMove from a FEN string
// ============================================================
function parseFen(fen) {
  const parts = fen.split(" ");
  const rows  = parts[0].split("/");
  const stm   = parts[1] === "w" ? "white" : "black";
  const board = {};

  rows.forEach((row, rowIdx) => {
    const rank = 8 - rowIdx;
    let fileIdx = 0;
    for (const ch of row) {
      if (ch >= "1" && ch <= "8") {
        fileIdx += parseInt(ch, 10);
      } else {
        board[FILES[fileIdx] + rank] = FEN_PIECE[ch];
        fileIdx++;
      }
    }
  });

  return { board, sideToMove: stm };
}

// ============================================================
// Board scaffold — squares layer + coordinates
// ============================================================
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
      const sq   = `${file}${rank}`;
      const tile = document.createElement("button");
      tile.type      = "button";
      tile.className = `square ${isDarkSquare(sq) ? "dark" : "light"}`;
      tile.dataset.square = sq;
      tile.setAttribute("aria-label", sq);
      tile.addEventListener("click", () => handleSquareClick(sq));
      squaresLayer.appendChild(tile);
    }
  }
}

// ============================================================
// Piece layer
// ============================================================
function isDarkSquare(sq) {
  const fi = FILES.indexOf(sq[0]);
  const ri = Number(sq[1]) - 1;
  return (fi + ri) % 2 === 0;
}

function squarePercent(sq) {
  const fi = FILES.indexOf(sq[0]);
  const ri = Number(sq[1]) - 1;
  return {
    tx: (isFlipped ? 7 - fi : fi) * 100,
    ty: (isFlipped ? ri : 7 - ri) * 100,
  };
}

function setPieceTransform(el, sq, immediate = false) {
  const { tx, ty } = squarePercent(sq);
  if (immediate) {
    const prev = el.style.transition;
    el.style.transition = "none";
    el.style.transform = `translate(${tx}%, ${ty}%)`;
    void el.offsetWidth;
    el.style.transition = prev;
  } else {
    el.style.transform = `translate(${tx}%, ${ty}%)`;
  }
  el.style.setProperty("--tx", `${tx}%`);
  el.style.setProperty("--ty", `${ty}%`);
}

function clearPieces() {
  for (const id of Object.keys(pieceById)) pieceById[id].element.remove();
  pieceMap  = {};
  pieceById = {};
  pieceIdSeq = 0;
}

function spawnPiece(sq, piece) {
  const id = `p${pieceIdSeq++}`;
  const el = document.createElement("div");
  el.className  = `piece ${piece.color} ${piece.kind}`;
  el.textContent = PIECE_SYMBOLS[piece.color][piece.kind];
  piecesLayer.appendChild(el);
  setPieceTransform(el, sq, true);
  pieceMap[sq]  = id;
  pieceById[id] = { square: sq, color: piece.color, kind: piece.kind, element: el };
  return id;
}

function rebuildAllPieces(board) {
  clearPieces();
  for (const [sq, piece] of Object.entries(board)) spawnPiece(sq, piece);
}

// ============================================================
// Highlights
// ============================================================
function renderHighlights() {
  const lastMove = moveHistory.length > 0
    ? { from: moveHistory[moveHistory.length - 1].slice(0, 2),
        to:   moveHistory[moveHistory.length - 1].slice(2, 4) }
    : null;

  for (const tile of squaresLayer.children) {
    tile.classList.remove("selected", "legal", "capture");
    delete tile.dataset.lastMove;
  }
  if (lastMove) {
    const f = squaresLayer.querySelector(`[data-square="${lastMove.from}"]`);
    const t = squaresLayer.querySelector(`[data-square="${lastMove.to}"]`);
    if (f) f.dataset.lastMove = "from";
    if (t) t.dataset.lastMove = "to";
  }
  if (selectedSquare) {
    const sel = squaresLayer.querySelector(`[data-square="${selectedSquare}"]`);
    if (sel) sel.classList.add("selected");
  }
}

// ============================================================
// Status & move list
// ============================================================
function renderStatus() {
  const isActive = gameStatus === "active";
  if (isActive) {
    turnText.textContent = `Tura: ${sideToMove === "white" ? "Albe" : "Negre"}`;
  } else {
    turnText.textContent = labelForStatus(gameStatus);
  }
  turnPill.dataset.turn = isActive ? sideToMove : "none";
}

function labelForStatus(s) {
  if (s === "white_win") return "Albele câștigă";
  if (s === "black_win") return "Negrele câștigă";
  if (s === "draw")      return "Remiză";
  if (s === "aborted")   return "Joc anulat";
  return "Joc terminat";
}

function labelForReason(r) {
  const MAP = {
    checkmate:           "Șah-mat",
    stalemate:           "Pat",
    resignation:         "Abandon",
    draw_50_move:        "Regula 50 mutări",
    draw_insufficient:   "Material insuficient",
    draw_threefold:      "Repetiție triplă",
    timeout:             "Timp depășit",
    engine_error:        "Eroare motor",
    engine_illegal_move: "Mutare ilegală (motor)",
  };
  return r ? (MAP[r] || r) : "";
}

function renderMoves() {
  moveCountBadge.textContent = moveHistory.length;
  movesEmpty.style.display   = moveHistory.length === 0 ? "block" : "none";
  movesList.innerHTML = "";
  const last = moveHistory.length - 1;

  for (let i = 0; i < moveHistory.length; i += 2) {
    const li = document.createElement("li");

    const num = document.createElement("span");
    num.className   = "ply-num";
    num.textContent = `${i / 2 + 1}.`;
    li.appendChild(num);

    const w = document.createElement("span");
    w.className   = "ply" + (i === last ? " latest" : "");
    w.textContent = moveHistory[i];
    li.appendChild(w);

    const b = document.createElement("span");
    if (moveHistory[i + 1] !== undefined) {
      b.className   = "ply" + (i + 1 === last ? " latest" : "");
      b.textContent = moveHistory[i + 1];
    } else {
      b.className   = "ply empty";
      b.textContent = "...";
    }
    li.appendChild(b);

    movesList.appendChild(li);
  }
  movesList.scrollTop = movesList.scrollHeight;
}

function renderPlayerCards() {
  const username   = userNameEl.textContent || "Tu";
  const botColor   = userColor === "white" ? "black" : "white";
  const levelLabel = botLevel ? `Niv. ${botLevel}` : "";

  // Which card is at the top vs. bottom depends on flip state.
  // Without flip: white is at bottom; with flip: black is at bottom.
  const userAtBottom = !isFlipped
    ? userColor === "white"
    : userColor === "black";

  const [userCard, botCard] = userAtBottom
    ? [{ name: bottomNameEl, color: bottomColorEl, dot: bottomDotEl, badge: bottomBadgeEl },
       { name: topNameEl,    color: topColorEl,    dot: topDotEl,    badge: topBadgeEl }]
    : [{ name: topNameEl,    color: topColorEl,    dot: topDotEl,    badge: topBadgeEl },
       { name: bottomNameEl, color: bottomColorEl, dot: bottomDotEl, badge: bottomBadgeEl }];

  userCard.name.textContent  = username;
  userCard.color.textContent = userColor === "white" ? "Albe" : "Negre";
  userCard.dot.className     = `player-dot ${userColor}`;
  userCard.badge.hidden      = true;

  botCard.name.textContent   = "BOT";
  botCard.color.textContent  = botColor === "white" ? "Albe" : "Negre";
  botCard.dot.className      = `player-dot ${botColor}`;
  botCard.badge.textContent  = levelLabel;
  botCard.badge.hidden       = !levelLabel;
}

function renderGameInfo() {
  infoLevel.textContent = botLevel ? `Nivel ${botLevel}` : "—";
  infoColor.textContent = userColor === "white" ? "Albe" : userColor === "black" ? "Negre" : "—";

  const statusMap = {
    active:    "În joc",
    white_win: "Albele câștigă",
    black_win: "Negrele câștigă",
    draw:      "Remiză",
    aborted:   "Anulat",
  };
  infoStatus.textContent = statusMap[gameStatus] || gameStatus;

  // Colour-code outcome for the user
  if (gameStatus !== "active" && userColor) {
    const won = (gameStatus === "white_win" && userColor === "white") ||
                (gameStatus === "black_win" && userColor === "black");
    infoStatus.className = won ? "game-info-value win"
                         : gameStatus === "draw" ? "game-info-value"
                         : "game-info-value loss";
  } else {
    infoStatus.className = "game-info-value";
  }

  if (resultReason) {
    infoReason.textContent = labelForReason(resultReason);
    infoReasonRow.hidden   = false;
  } else {
    infoReasonRow.hidden = true;
  }
}

function renderResignButton() {
  resignBtn.hidden = gameStatus !== "active";
}

// ============================================================
// Apply a full game-state payload from any /games/* response
// ============================================================
function applyGameState(data) {
  moveHistory  = data.moves         || [];
  gameStatus   = data.status        || "active";
  resultReason = data.result_reason || null;
  botLevel     = data.bot_level     || botLevel;
  if (data.user_color) userColor = data.user_color;

  const { board, sideToMove: stm } = parseFen(data.fen);
  currentBoard = board;
  sideToMove   = stm;

  rebuildAllPieces(currentBoard);
  renderHighlights();
  renderStatus();
  renderMoves();
  renderPlayerCards();
  renderGameInfo();
  renderResignButton();

  if (gameStatus !== "active" && !endgameSeen) {
    endgameSeen = true;
    showEndgameModal();
  }
}

function showEndgameModal() {
  const userWon = (gameStatus === "white_win" && userColor === "white") ||
                  (gameStatus === "black_win" && userColor === "black");
  const isDraw  = gameStatus === "draw";

  if (isDraw) {
    endgameIcon.textContent  = "\u00BD";
    endgameTitle.textContent = "Remiză";
    endgameText.textContent  = labelForReason(resultReason) || "Partida s-a terminat la egalitate.";
  } else if (userWon) {
    endgameIcon.textContent  = "\u265A";
    endgameTitle.textContent = "Victorie!";
    endgameText.textContent  = labelForReason(resultReason) || "Ai câștigat partida!";
  } else if (resultReason === "resignation") {
    endgameIcon.textContent  = "\u2691";
    endgameTitle.textContent = "Abandon";
    endgameText.textContent  = "Ai abandonat partida.";
  } else if (gameStatus === "aborted") {
    endgameIcon.textContent  = "\u2716";
    endgameTitle.textContent = "Joc anulat";
    endgameText.textContent  = labelForReason(resultReason) || "";
  } else {
    endgameIcon.textContent  = "\u265A";
    endgameTitle.textContent = "Înfrângere";
    endgameText.textContent  = labelForReason(resultReason) || "Botul câștigă partida.";
  }
  endgameModal.hidden = false;
}

// ============================================================
// Board interaction
// ============================================================
function isUserTurn() {
  return gameStatus === "active" && sideToMove === userColor;
}

async function handleSquareClick(sq) {
  if (interactionLocked || pendingPromotion) return;
  if (!isUserTurn()) {
    // Give a polite hint instead of silent ignore
    if (gameStatus !== "active") return;
    setMessage("Botul gândește — așteaptă tura ta.", "info");
    return;
  }

  const piece = currentBoard[sq];

  // If a square is already selected, try to make a move to `sq`
  if (selectedSquare) {
    if (selectedSquare === sq) {
      // Deselect on second click of same square
      selectedSquare = null;
      renderHighlights();
      return;
    }

    // Check for pawn promotion
    const movingPiece = currentBoard[selectedSquare];
    if (movingPiece && movingPiece.kind === "pawn") {
      const targetRank = Number(sq[1]);
      if ((movingPiece.color === "white" && targetRank === 8) ||
          (movingPiece.color === "black" && targetRank === 1)) {
        openPromotionModal(selectedSquare, sq, movingPiece.color);
        return;
      }
    }

    await doSubmitMove(selectedSquare, sq, null);
    return;
  }

  // Select a piece belonging to the user
  if (piece && piece.color === userColor) {
    selectedSquare = sq;
    setMessage("");
    renderHighlights();
    return;
  }

  setMessage("");
}

async function doSubmitMove(from, to, promotion) {
  const uci = from + to + (promotion || "");
  interactionLocked = true;
  selectedSquare    = null;
  setMessage("");

  try {
    showBotThinking(true);
    const data = await GamesAPI.submitMove(gameId, uci);
    applyGameState(data);
  } catch (err) {
    renderHighlights();  // restore last-move highlight
    const msg = (err.data && err.data.error) || err.message || "Mutare ilegală.";
    setMessage(msg);
  } finally {
    showBotThinking(false);
    setTimeout(() => { interactionLocked = false; }, 280);
  }
}

function showBotThinking(visible) {
  botThinking.hidden = !visible;
  boardEl.classList.toggle("waiting-for-bot", visible);
}

// ============================================================
// Promotion modal
// ============================================================
function openPromotionModal(from, to, color) {
  pendingPromotion = { from, to };
  promoChoices.innerHTML = "";
  for (const kind of ["queen", "rook", "bishop", "knight"]) {
    const btn = document.createElement("button");
    btn.type        = "button";
    btn.className   = color;
    btn.textContent = PIECE_SYMBOLS[color][kind];
    btn.title       = kind;
    btn.addEventListener("click", () => choosePromotion(kind[0]));  // "q","r","b","n"
    promoChoices.appendChild(btn);
  }
  promoModal.hidden = false;
}

async function choosePromotion(piece) {
  const promo = pendingPromotion;
  pendingPromotion = null;
  promoModal.hidden = true;
  if (!promo) return;
  await doSubmitMove(promo.from, promo.to, piece);
}

// ============================================================
// Resign
// ============================================================
async function performResign() {
  if (interactionLocked || gameStatus !== "active") return;
  if (!confirm("Abandonezi partida? Această acțiune nu poate fi anulată.")) return;

  interactionLocked = true;
  try {
    const data = await GamesAPI.resignGame(gameId);
    applyGameState(data);
  } catch (err) {
    setMessage((err.message) || "Eroare la abandon.");
  } finally {
    setTimeout(() => { interactionLocked = false; }, 200);
  }
}

// ============================================================
// Flip
// ============================================================
function performFlip() {
  isFlipped = !isFlipped;
  rebuildSquaresLayout();
  rebuildCoords();
  for (const id of Object.keys(pieceById)) {
    setPieceTransform(pieceById[id].element, pieceById[id].square, true);
  }
  renderHighlights();
  renderPlayerCards();
}

// ============================================================
// Start a new game (from setup form)
// ============================================================
async function startGame() {
  setupErrorEl.textContent = "";
  startBtn.disabled = true;

  try {
    const data = await GamesAPI.createBotGame(setupDraft.color, setupDraft.level);

    gameId    = data.game_id;
    userColor = data.user_color;
    isFlipped = userColor === "black";
    endgameSeen = false;

    showGameScreen();
    buildBoardScaffold();
    applyGameState(data);

    history.replaceState(null, "", `/bot?id=${gameId}`);
  } catch (err) {
    if (err.status === 401) { authModalEl.hidden = false; return; }
    setupErrorEl.textContent = (err.data && err.data.error) || err.message || "Nu pot porni jocul.";
  } finally {
    startBtn.disabled = false;
  }
}

// ============================================================
// Load an existing game by ID (e.g. from ?id= URL param)
// ============================================================
async function loadGame(id) {
  try {
    const data = await GamesAPI.getGame(id);

    gameId    = data.game_id || id;
    userColor = data.user_color;
    isFlipped = userColor === "black";
    endgameSeen = false;

    showGameScreen();
    buildBoardScaffold();
    applyGameState(data);
  } catch (err) {
    if (err.status === 401) { authModalEl.hidden = false; return; }
    const msg = (err.status === 404 || err.status === 403)
      ? "Jocul nu există sau nu îți aparține."
      : (err.message || "Nu pot încărca jocul.");
    setupErrorEl.textContent = msg;
    showSetupScreen();
  }
}

// ============================================================
// Screen transitions
// ============================================================
function showGameScreen() {
  setupScreenEl.hidden = true;
  gameScreenEl.hidden  = false;
}

function showSetupScreen() {
  setupScreenEl.hidden = false;
  gameScreenEl.hidden  = true;
  // Reset transient state
  selectedSquare    = null;
  interactionLocked = false;
  pendingPromotion  = null;
  gameId            = null;
  endgameSeen       = false;
  setMessage("");
  history.replaceState(null, "", "/bot");
}

// ============================================================
// Utility
// ============================================================
function setMessage(text, kind = "error") {
  messageEl.textContent = text || "";
  messageEl.className   = "message" + (text ? " " + kind : "");
}

// ============================================================
// Wire up controls
// ============================================================
document.querySelector("#color-choices").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-color]");
  if (!btn) return;
  setupDraft.color = btn.dataset.color;
  for (const b of document.querySelectorAll("#color-choices .pill"))
    b.classList.toggle("selected", b.dataset.color === setupDraft.color);
});

document.querySelector("#level-choices").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-level]");
  if (!btn) return;
  setupDraft.level = Number(btn.dataset.level);
  for (const b of document.querySelectorAll("#level-choices .pill"))
    b.classList.toggle("selected", Number(b.dataset.level) === setupDraft.level);
});

startBtn.addEventListener("click", startGame);
newGameBtn.addEventListener("click", () => { endgameModal.hidden = true; showSetupScreen(); });
resignBtn.addEventListener("click", performResign);
flipBtn.addEventListener("click", performFlip);
endgameClose.addEventListener("click", () => { endgameModal.hidden = true; });
endgameNew.addEventListener("click",   () => { endgameModal.hidden = true; showSetupScreen(); });

// ============================================================
// Boot: check auth then load or show setup
// ============================================================
async function checkAuthAndLoad() {
  if (!GamesAPI.hasToken()) {
    authModalEl.hidden = false;
    return;
  }

  // Validate the stored token and load the username
  try {
    const res  = await fetch("/auth/me", {
      headers: { Authorization: `Bearer ${localStorage.getItem("chessmate_token")}` },
    });
    const data = await res.json();
    if (!data.ok) throw new Error("token invalid");
    userNameEl.textContent = data.user.username;
    userChipEl.hidden      = false;
  } catch {
    authModalEl.hidden = false;
    return;
  }

  // Check for a game ID in the URL
  const params  = new URLSearchParams(location.search);
  const idParam = params.get("id");
  if (idParam && !isNaN(Number(idParam))) {
    await loadGame(Number(idParam));
  } else {
    showSetupScreen();
  }
}

checkAuthAndLoad();
