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
