#!/usr/bin/env sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_DIR"

PYTHON_BIN=${PYTHON_BIN:-python3}
VENV_DIR=${VENV_DIR:-.venv}
REQUESTED_PORT=${PORT+x}
HOST=${HOST:-127.0.0.1}
PORT=${PORT:-5000}
FLASK_DEBUG=${FLASK_DEBUG:-1}
MP_PORT=${MP_PORT:-8000}

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "Creating virtual environment in $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "Installing dependencies"
"$VENV_DIR/bin/python" -m pip install -r requirements.txt

is_port_available() {
  "$VENV_DIR/bin/python" - "$HOST" "$1" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sys.exit(1)
PY
}

if [ -z "$REQUESTED_PORT" ]; then
  candidate=$PORT
  while ! is_port_available "$candidate"; do
    candidate=$((candidate + 1))
    if [ "$candidate" -gt 5099 ]; then
      echo "No free port found between $PORT and 5099" >&2
      exit 1
    fi
  done

  if [ "$candidate" != "$PORT" ]; then
    echo "Port $PORT is busy; using $candidate"
    PORT=$candidate
  fi
fi

echo "Starting ChessMate Sprint 3 at http://$HOST:$PORT"
echo "Starting multiplayer service at http://$HOST:$MP_PORT"
MP_PORT="$MP_PORT" MP_HOST="$HOST" "$VENV_DIR/bin/python" -m uvicorn multiplayer.main:app --host "$HOST" --port "$MP_PORT" &
MP_PID=$!
trap 'kill "$MP_PID"' EXIT
HOST="$HOST" PORT="$PORT" FLASK_DEBUG="$FLASK_DEBUG" MP_PORT="$MP_PORT" MP_HOST="$HOST" "$VENV_DIR/bin/python" app.py
