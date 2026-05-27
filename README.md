# ChessMate — Sprint 3 (v4)

Joc de sah local. Sprint 3 adauga modul **Contra bot** (jucator vs motor)
peste cele 1v1 local existente. Modulul motor (`chessmate/engine.py`)
implementeaza Monte Carlo Tree Search ca baseline — slab in mod intentionat,
dar construit ca punct de pornire usor de extins.

Nu include: multiplayer online, autentificare, baza de date, WebSocket,
statistici persistente. Restrictiile din PoC raman in vigoare.

## Ce este nou in v4

- **Selectare mod de joc** la prima incarcare (modal): 1v1 Local sau Contra bot.
  Schimbarea modului oricand prin butonul "1v1 Local" / "Contra bot" din topbar.
- **Motor de joc**: Monte Carlo Tree Search cu evaluare material+tanh (intentionat
  slab, dar construit modular pentru a fi inlocuit/imbunatatit usor).
- **Reguli complete FIDE**: pe langa sah-mat / pat din Sprint 2, se detecteaza
  acum si:
  - material insuficient (KvK, KvK+nebun, KvK+cal, nebuni pe acelasi culoare),
  - regula celor 50 de mutari (100 de semimutari fara captura sau mutare de pion),
  - repetitie tripla a aceleiasi pozitii.
- **Anulare inteligenta in mod bot**: Undo intoarce doua semimutari, astfel incat
  jucatorul revine la randul lui (nu in pozitia in care botul tocmai a mutat).
- **Overlay "Bot gandeste"** pe tabla cat timp motorul calculeaza.

## Arhitectura motorului

`chessmate/engine.py` defineste:

- `Engine` — interfata abstracta; o singura metoda `choose_move(game)` ce
  intoarce o tupla `(origin, destination, promotion)`.
- `MCTSEngine(simulations=120, rollout_depth=10, time_budget=1.5, exploration=1.4, seed)` —
  MCTS clasic cu UCT, rollouts aleatoare cu adancime limitata si evaluare
  material la frunza. Parametri conservativi: maxim 120 simulari / 1.5s per mutare.
- `build_engine(name="mcts", **kwargs)` — factory pentru construirea unui motor.
  In acest moment doar MCTS este disponibil; factory-ul ramane pentru a permite
  adaugarea altor motoare in viitor fara modificari la apelanti.

Motorul nu detine stare proprie a jocului; foloseste fast-path-ul
`ChessGame.engine_make_move` / `engine_undo` care evita constructia SAN si
scanarea sah-mat/draw la fiecare iteratie din arbore.

Puncte naturale de extindere pentru iteratii viitoare:
- evaluator mai bun in `MCTSEngine._material_eval` (PST, mobilitate, siguranta rege),
- ordonare mutari in rollout policy (acum complet random),
- tabel de transpozitie / Zobrist hashing,
- adaugare unui `MinimaxEngine` (alpha-beta) pe langa MCTS.

## Functii (recapitulare)

Backend (`chessmate/core.py`):
- generare si validare mutari pentru toate piesele,
- detectare sah, sah-mat, pat, material insuficient, 50 mutari, repetitie tripla,
- rocada (scurta si lunga), en passant, promovare pion (default dama),
- istoric in notatie algebrica standard (SAN),
- undo pentru ultima mutare (restaureaza complet starea — inclusiv drepturi
  de rocada, target en passant, contor 50-mutari, contor repetitii).

Frontend (`static/`):
- modal de selectare mod la incarcare + buton dedicat in topbar,
- animatii smooth ale pieselor (FLIP-style),
- evidentiere ultima mutare + puls rosu pe regele in sah,
- panou lateral cu istoricul mutarilor,
- piese capturate pe lateral, sortate dupa valoare, cu avantaj material,
- modal de promovare (Dama/Turn/Nebun/Cal),
- modal de final de joc (sah-mat / pat / material insuficient / 50 mutari / repetitie),
- overlay "Bot gandeste..." cu spinner peste tabla,
- buton Undo, Flip board, Joc nou,
- responsive (desktop + mobile).

## Rulare

```bash
./local-setup.sh
```

Aplicatia porneste pe `http://127.0.0.1:5000`.
Daca portul implicit e ocupat si `PORT` nu este setat manual, scriptul alege
automat urmatorul port liber.

```bash
PORT=5001 HOST=0.0.0.0 ./local-setup.sh
```

## Teste

```bash
python3 -m unittest discover -s tests
```

Suita de teste e impartita in:
- `tests/test_core.py` — reguli sah + tot ce e nou in Sprint 3 (toate mutarile
  legale, material insuficient, 50 mutari, repetitie tripla, fast-path engine),
- `tests/test_api.py` — endpoint-uri Flask + sesiunea (mod, culoare bot, motor),
- `tests/test_engine.py` — smoke tests pentru `MCTSEngine` si `build_engine`
  (cu numar mic de simulari pentru viteza).

Testele care depind de Flask se sar automat daca Flask nu este instalat.

## API

- `GET  /api/state` — starea completa a jocului (include `session: {mode, botColor, engine}`)
- `GET  /api/moves?from=<sq>` — mutarile legale pentru piesa de pe patratul `<sq>`
- `POST /api/move` — trimite o mutare a jucatorului: `{"from": "e2", "to": "e4", "promotion": "queen"}`
  - `promotion` e optional, folosit doar pentru pion care ajunge pe ultimul rand.
  - In modul `vs_bot`, endpoint-ul refuza mutarile pentru culoarea botului.
- `POST /api/bot_move` — cere motorului sa joace mutarea curenta (doar in `vs_bot`,
  doar cand e randul botului).
- `POST /api/new_game` — porneste un joc nou cu mod ales:
  `{"mode": "local" | "vs_bot", "botColor": "white" | "black"}`
  - `botColor` este cerut doar pentru `vs_bot`. Motorul este intotdeauna MCTS.
- `POST /api/undo` — anuleaza ultima mutare (doua semimutari in `vs_bot`).
- `POST /api/reset` — reseteaza tabla, pastrand modul curent.

## In-house engine (`engine/`)

A second, stronger engine lives in `engine/`, written from scratch (no external
chess libraries) as a classical alpha-beta core. It is independent of the
existing `chessmate/` MCTS engine and can be used directly or wired into the
Flask layer.

Features:

- negamax + alpha-beta with iterative deepening
- transposition table (Zobrist hashing)
- quiescence search (captures + promotions)
- move ordering: TT move → MVV-LVA captures → killers → history
- null-move pruning + check extensions + PVS-lite
- handcrafted eval: material, PST (tapered MG/EG king), mobility, bishop pair,
  doubled/isolated/passed pawns, rook on open/semi-open file, king pawn-shield
  and attacker count, tempo
- legal: castling, en passant, promotion, 50-move rule, threefold repetition,
  insufficient material
- 3 difficulty levels exposed by `best_move(..., level=1|2|3|4)` that scale
  the search budget and randomness — never the rules

### Python API

```python
from engine import best_move, analyze_position

best_move("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
          time_ms=1000, level=3)
# {'move': 'e2e4', 'from': 'e2', 'to': 'e4', 'promotion': None,
#  'score_cp': 32, 'mate': None, 'depth': 7, 'nodes': 12345,
#  'time_ms': 998, 'pv': ['e2e4', 'e7e5', ...], 'source': 'search'}

analyze_position(fen, depth=8)
```

### UCI-like CLI

```bash
python -m engine.uci
```

Supports `uci`, `isready`, `ucinewgame`, `position startpos [moves ...]`,
`position fen ... moves ...`, `go movetime N | depth N | wtime/btime/winc/binc`,
`stop`, `quit`, plus `d` (print board) and `eval`.

## Data tools (`tools/`)

Offline scripts to extract value from the Kaggle `lichess-08-2014.csv` CSV.
They may use `python-chess` (only here) for robust PGN/SAN parsing.

```bash
# 1) Normalize the Kaggle CSV into JSONL (one game per line).
python -m tools.parse_kaggle_games \
    --in lichess-08-2014.csv --out data/games.jsonl \
    --min-rating 1600

# 2) Build an opening book keyed by our engine's Zobrist hash.
python -m tools.build_opening_book \
    --in data/games.jsonl --out data/opening_book.json \
    --max-ply 16 --min-rating 1700 --min-freq 3 --top-k 6
# The engine auto-loads data/opening_book.json on first probe.

# 3) Label every move with Best / Excellent / Good / Inaccuracy / Mistake / Blunder
python -m tools.label_moves \
    --in data/games.jsonl --out data/labeled.jsonl \
    --time-ms 80 --max-games 500

# 4) Mine puzzle candidates from blunders.
python -m tools.extract_puzzles \
    --labeled data/labeled.jsonl --games data/games.jsonl \
    --out data/puzzles.jsonl --min-swing 250 --solution-plies 4

# 5) Train a tiny supervised policy net (optional).
python -m tools.train_policy_small \
    --in data/games.jsonl --out models/policy.pt \
    --epochs 2 --batch 128 --max-positions 200000
```

The opening book and tiny policy model are optional enhancements — the engine
runs without either. Move-labeling thresholds (in centipawns vs the engine's
best move): Best ≤ 20, Excellent 21–50, Good 51–100, Inaccuracy 101–250,
Mistake 251–500, Blunder > 500 (or mate-swings). cp values are capped before
labeling to avoid spurious "Blunder" tags in already-won positions.

## Structura

```
chessmatev2/
├── app.py                   # server Flask + sesiune (mod + motor)
├── chessmate/
│   ├── __init__.py
│   ├── core.py              # motor reguli + stare
│   └── engine.py            # MCTSEngine + build_engine
├── static/                  # UI web
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── tests/
│   ├── test_core.py
│   ├── test_api.py
│   └── test_engine.py
├── docs/                    # documente specificatie / arhitectura
├── requirements.txt
└── local-setup.sh           # instalare + rulare intr-un singur pas
```
