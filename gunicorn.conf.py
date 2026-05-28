"""Gunicorn configuration for ChessMate.

Auto-loaded by gunicorn when present in the working directory, so the literal
`gunicorn app:app` start command binds to Render's $PORT and uses safe defaults.
"""

import os

# Render (and most PaaS) inject the port to listen on via $PORT.
bind = "0.0.0.0:" + os.environ.get("PORT", "8000")

# The play page keeps a single in-process game session (app.py), so we run ONE
# worker to avoid splitting that state across processes. Concurrency comes from
# threads instead.
workers = 1
threads = int(os.environ.get("WEB_THREADS", "8"))

# Game analysis (POST /games/<id>/analyze) runs the engine synchronously and can
# take tens of seconds, so allow a generous request timeout.
timeout = int(os.environ.get("WEB_TIMEOUT", "180"))
graceful_timeout = 30
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
