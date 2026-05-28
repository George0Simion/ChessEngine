# ChessMate

A Flask chess web app: play the in-house engine (4 levels), local 1v1, online
multiplayer, Lichess puzzles, plus game history, review and engine-powered move
analysis. The engine (`engine/`) is a from-scratch alpha-beta core; the live
multiplayer server (`multiplayer/`) is a separate FastAPI/WebSocket service.

## Architecture

| Component | Tech | Entry point |
|---|---|---|
| Web app (bot, local, puzzles, history, review, analysis) | Flask + SQLAlchemy | `app:app` (WSGI) |
| Live online multiplayer | FastAPI + WebSocket | `multiplayer.main:app` (ASGI) |
| Chess engine | pure Python alpha-beta | `engine/` (library) |
| Database | Postgres (prod) / SQLite (local) | `models.py` |

Both services share the same database and the same JWT secret so a token issued
by the web app authenticates the WebSocket connection.

## Run locally

One-step script (creates a venv, installs deps, starts both services):

```bash
./local-setup.sh
```

Web app on `http://127.0.0.1:5000`, multiplayer on `http://127.0.0.1:8000`.

Manual, production-style (single web service via gunicorn):

```bash
pip install -r requirements.txt
gunicorn app:app                 # binds 0.0.0.0:$PORT (default 8000)
```

Copy `.env.example` to `.env` to set secrets/config locally; it's loaded
automatically.

## Deploy on Render

The repo ships a `render.yaml` Blueprint that provisions a Postgres database, a
shared secret group, and two web services.

- **Build command:** `pip install -r requirements.txt`
- **Start command (web):** `gunicorn app:app`
- **Start command (multiplayer):** `uvicorn multiplayer.main:app --host 0.0.0.0 --port $PORT`

Steps:

1. Push this repo to GitHub and create a new **Blueprint** on Render pointing at
   it (or create the services manually with the commands above).
2. Render creates `chessmate-db`, the `chessmate-secrets` group (random
   `SECRET_KEY` + `JWT_SECRET_KEY` shared by both services), and the two web
   services with `DATABASE_URL` wired in.
3. After the **multiplayer** service is live, copy its URL and set
   `MP_WS_URL=wss://<chessmate-mp-host>/ws` on the **web** service, then redeploy
   the web service. (The mp URL isn't known until its first deploy, so this env
   var is intentionally left unset in the Blueprint.)

`gunicorn app:app` works without extra flags because `gunicorn.conf.py` binds to
`0.0.0.0:$PORT`. The web service runs a **single worker** (the play page keeps an
in-process game session) with multiple threads, and a long request timeout
because game analysis runs synchronously.

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `SECRET_KEY` | yes (prod) | Flask session + default JWT secret. |
| `JWT_SECRET_KEY` | recommended | JWT signing key; falls back to `SECRET_KEY`. Must match across both services. |
| `DATABASE_URL` | prod | Postgres URL. If unset, falls back to local SQLite. `postgres://` is auto-normalized to `postgresql://`. |
| `FLASK_ENV` | no | Set `production` to keep debug off (default). `development` enables debug for `python app.py`. |
| `DATA_DIR` | no | Directory for persistent runtime files (SQLite fallback DB + analysis cache). Defaults to `./instance`. |
| `MP_WS_URL` | prod (multiplayer) | Public `wss://…/ws` URL of the multiplayer service, set on the web service. |
| `PORT` | auto | Provided by Render; gunicorn/uvicorn bind to it. |
| `MP_PORT` | local only | Port for the local multiplayer process (default 8000). |

### Database notes

- **Production:** set `DATABASE_URL` to a Postgres connection string (the
  Blueprint does this automatically via `chessmate-db`). Tables are created on
  startup (`db.create_all()` + a lightweight column-add for older schemas).
- **Local:** with no `DATABASE_URL`, the app uses SQLite at
  `<DATA_DIR or instance>/chessmate.db`.

### Persistent files / disk notes

Game analysis is cached as JSON under `<DATA_DIR or instance>/analyses/`. On
Render's default filesystem this is **ephemeral** (cleared on restart/redeploy),
which is fine because any analysis can simply be re-run. To make it (and a SQLite
DB, if you choose SQLite over Postgres) survive restarts, attach a Render disk and
set `DATA_DIR` to its mount path (e.g. `/var/data`). Disks require a paid instance
and pin the service to a single instance.

## Project layout

```
app.py                # Flask app factory + /api/* + page routes (WSGI: app:app)
auth.py               # JWT auth blueprint (/auth/*)
models.py             # SQLAlchemy models (User, Rating, Game)
backend/games.py      # /games/* : history, record, review-data, analyze
engine/               # in-house alpha-beta engine (untouched library)
chessmate/            # board rules/state + puzzle loader
multiplayer/          # FastAPI WebSocket server (online play)
static/               # frontend (index, play, profile, review, puzzles)
gunicorn.conf.py      # binds $PORT, 1 worker + threads, long timeout
render.yaml           # Render Blueprint (db + 2 services + secret group)
Procfile              # web: gunicorn app:app
requirements.txt
```

## Limitations

- Live multiplayer is a **separate** service; the `gunicorn app:app` web service
  alone covers bot, local, puzzles, history, review and analysis.
- The web service is single-worker by design (shared in-process game session).
- The analysis cache is ephemeral unless a disk is mounted at `DATA_DIR`.
