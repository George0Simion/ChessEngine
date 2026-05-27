# Multiplayer service (FastAPI)

This service provides online multiplayer with WebSocket, matchmaking, and
server-authoritative clocks. It runs separately from the Flask app to keep
changes isolated.

## Run

```
uvicorn multiplayer.main:app --host 0.0.0.0 --port 8000
```

Environment variables:
- DATABASE_URL (same as Flask)
- SECRET_KEY (same as Flask, used for JWT validation)
- MP_DISCONNECT_GRACE (optional, seconds; default 45)

## Time control

- Allowed base minutes: 3, 5, 10
- Increment: 2 seconds

## WebSocket protocol

Client must authenticate first:

```
{"type": "auth", "token": "<jwt>"}
```

Server replies:

```
{"type": "auth_ok", "user": {"id": 1, "username": "alice", "rating": 1500}}
```

### Queue

```
{"type": "join_queue", "minutes": 3}
{"type": "cancel_queue"}
```

Responses:

```
{"type": "queued", "minutes": 3, "incrementSec": 2}
{"type": "match_found", "roomId": "...", "color": "white", "opponent": {...},
 "timeControl": {"baseMin": 3, "incrementSec": 2}, "state": {...}, "clock": {...}}
```

### Moves

```
{"type": "move", "from": "e2", "to": "e4", "promotion": "queen"}
```

Server broadcasts:

```
{"type": "state", "roomId": "...", "state": {...}, "clock": {...}}
```

### Clock

Server broadcasts every second:

```
{"type": "clock", "roomId": "...", "clock": {"white": 180, "black": 180, "active": "white"}}
```

### End game

```
{"type": "game_over", "roomId": "...", "status": "checkmate", "winner": "white",
 "reason": "game_end", "state": {...}, "clock": {...}}
```

### Disconnect/reconnect

If a player disconnects, the opponent receives:

```
{"type": "opponent_left", "roomId": "...", "graceSec": 45}
```

If the player returns within the grace window:

```
{"type": "reconnected", "roomId": "...", "color": "white", "opponent": {...},
 "state": {...}, "clock": {...}}
```
