from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .auth import authenticate_token
from .db import init_db
from .matchmaking import Matchmaker, QueueEntry
from .rooms import RoomManager
from .settings import ALLOWED_TIME_CONTROLS, DEFAULT_TIME_CONTROL, INCREMENT_SEC

app = FastAPI(title="ChessMate Multiplayer")

matchmaker = Matchmaker(ALLOWED_TIME_CONTROLS)
rooms = RoomManager()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/time-controls")
def time_controls() -> dict[str, Any]:
    return {
        "baseMinutes": sorted(ALLOWED_TIME_CONTROLS),
        "incrementSec": INCREMENT_SEC,
    }


async def _send_error(websocket: WebSocket, message: str) -> None:
    await websocket.send_json({"type": "error", "message": message})


async def _authenticate(websocket: WebSocket) -> Optional[dict[str, Any]]:
    try:
        msg = await asyncio.wait_for(websocket.receive_json(), timeout=15)
    except Exception:
        await websocket.close(code=1008)
        return None

    if msg.get("type") != "auth":
        await _send_error(websocket, "Expected auth message.")
        await websocket.close(code=1008)
        return None

    token = msg.get("token")
    if not token:
        await _send_error(websocket, "Missing token.")
        await websocket.close(code=1008)
        return None

    user = await asyncio.to_thread(authenticate_token, token)
    if not user:
        await _send_error(websocket, "Invalid token.")
        await websocket.close(code=1008)
        return None

    await websocket.send_json({"type": "auth_ok", "user": user})
    return user


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    user = await _authenticate(websocket)
    if not user:
        return

    room = await rooms.attach_if_active(user["id"], websocket)
    if room:
        await room.send_reconnected(user["id"])

    try:
        while True:
            try:
                msg = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                await _send_error(websocket, "Invalid message.")
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type == "join_queue":
                if await matchmaker.is_queued(user["id"]):
                    await _send_error(websocket, "Already in queue.")
                    continue
                if await rooms.get_room_for_user(user["id"]):
                    await _send_error(websocket, "Already in a game.")
                    continue

                minutes = msg.get("minutes", DEFAULT_TIME_CONTROL)
                if minutes not in ALLOWED_TIME_CONTROLS:
                    await _send_error(websocket, "Unsupported time control.")
                    continue

                entry = QueueEntry(user=user, websocket=websocket)
                match = await matchmaker.enqueue(entry, minutes)
                if not match:
                    await websocket.send_json({
                        "type": "queued",
                        "minutes": minutes,
                        "incrementSec": INCREMENT_SEC,
                    })
                    continue

                other, current = match
                room = await rooms.create_room(other, current, minutes, INCREMENT_SEC)
                await room.send_match_found()
                continue

            if msg_type == "cancel_queue":
                removed = await matchmaker.remove(user["id"])
                await websocket.send_json({"type": "queue_canceled", "removed": removed})
                continue

            if msg_type == "get_state":
                room = await rooms.get_room_for_user(user["id"])
                if not room:
                    await _send_error(websocket, "No active game.")
                    continue
                await room.send_state_to(user["id"])
                continue

            if msg_type == "moves":
                room = await rooms.get_room_for_user(user["id"])
                if not room:
                    await _send_error(websocket, "No active game.")
                    continue
                try:
                    origin = msg.get("from", "")
                    await room.send_moves(user["id"], origin)
                except Exception as exc:
                    await _send_error(websocket, str(exc))
                continue

            if msg_type == "move":
                room = await rooms.get_room_for_user(user["id"])
                if not room:
                    await _send_error(websocket, "No active game.")
                    continue
                try:
                    origin = msg.get("from", "")
                    target = msg.get("to", "")
                    promotion = msg.get("promotion")
                    await room.handle_move(user["id"], origin, target, promotion)
                except Exception as exc:
                    await _send_error(websocket, str(exc))
                continue

            if msg_type == "resign":
                room = await rooms.get_room_for_user(user["id"])
                if not room:
                    await _send_error(websocket, "No active game.")
                    continue
                await room.handle_resign(user["id"])
                continue

            if msg_type == "leave":
                room = await rooms.get_room_for_user(user["id"])
                if room:
                    await room.handle_resign(user["id"])
                continue

            await _send_error(websocket, "Unknown message type.")
    finally:
        await matchmaker.remove(user["id"])
        room = await rooms.get_room_for_user(user["id"])
        if room:
            await room.handle_disconnect(user["id"])
