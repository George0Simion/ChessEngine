from __future__ import annotations

import asyncio
import random
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from fastapi import WebSocket

from chessmate.core import BLACK, WHITE, ChessGame, InvalidMoveError, opponent
from .persistence import append_move, create_game_record, set_game_result
from .schemas import move_to_uci
from .settings import CLOCK_TICK_SEC, DISCONNECT_GRACE_SEC
from .timer import GameClock


@dataclass
class PlayerInfo:
    user_id: int
    username: str
    rating: Optional[int]
    color: str


@dataclass
class Room:
    room_id: str
    white: PlayerInfo
    black: PlayerInfo
    base_min: int
    increment_sec: int
    game_id: int
    game: ChessGame = field(default_factory=ChessGame)
    clock: GameClock = field(init=False)
    connections: dict[int, WebSocket] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    status: str = "active"
    winner: Optional[str] = None
    clock_task: Optional[asyncio.Task] = None
    disconnect_tasks: dict[int, asyncio.Task] = field(default_factory=dict)
    on_end: Optional[Callable[["Room"], Awaitable[None]]] = None

    def __post_init__(self) -> None:
        self.clock = GameClock(self.base_min * 60, self.increment_sec)

    def color_for(self, user_id: int) -> Optional[str]:
        if user_id == self.white.user_id:
            return WHITE
        if user_id == self.black.user_id:
            return BLACK
        return None

    def opponent_for(self, user_id: int) -> PlayerInfo:
        if user_id == self.white.user_id:
            return self.black
        return self.white

    def _player_payload(self, player: PlayerInfo) -> dict[str, object]:
        return {
            "id": player.user_id,
            "username": player.username,
            "rating": player.rating,
            "color": player.color,
        }

    def _decorate_state(self, state: dict[str, object]) -> dict[str, object]:
        session = {
            "mode": "multiplayer",
            "roomId": self.room_id,
            "timeControl": {
                "baseMin": self.base_min,
                "incrementSec": self.increment_sec,
            },
        }
        decorated = dict(state)
        decorated["session"] = session
        decorated["canUndo"] = False
        return decorated

    def clock_payload(self, *, update: bool = True) -> dict[str, object]:
        payload = self.clock.snapshot_payload(update=update)
        return {
            "white": payload[WHITE],
            "black": payload[BLACK],
            "active": payload["active"],
        }

    async def start(self) -> None:
        self.clock.start(WHITE)
        self.clock_task = asyncio.create_task(self._clock_loop())

    async def attach_connection(self, user_id: int, websocket: WebSocket) -> None:
        async with self.lock:
            self.connections[user_id] = websocket
            task = self.disconnect_tasks.pop(user_id, None)
            if task:
                task.cancel()
        opponent_info = self.opponent_for(user_id)
        await self._safe_send(
            opponent_info.user_id,
            {
                "type": "opponent_back",
                "roomId": self.room_id,
            },
        )

    async def detach_connection(self, user_id: int) -> None:
        async with self.lock:
            self.connections.pop(user_id, None)

    async def send_match_found(self) -> None:
        await self._safe_send(self.white.user_id, self._match_payload(self.white.user_id))
        await self._safe_send(self.black.user_id, self._match_payload(self.black.user_id))

    async def send_reconnected(self, user_id: int) -> None:
        await self._safe_send(user_id, self._reconnect_payload(user_id))

    async def send_state_to(self, user_id: int) -> None:
        await self._safe_send(user_id, self._state_payload())

    async def broadcast_state(self) -> None:
        await self._broadcast(self._state_payload())

    async def send_moves(self, user_id: int, origin: str) -> None:
        async with self.lock:
            color = self.color_for(user_id)
            if color is None:
                raise ValueError("Player is not part of this game.")
            if color != self.game.turn:
                raise ValueError("Not your turn.")
            try:
                moves = self.game.legal_moves_for(origin)
            except InvalidMoveError as exc:
                raise ValueError(str(exc)) from exc
            state = self._decorate_state(self.game.state())

        await self._safe_send(
            user_id,
            {
                "type": "moves",
                "roomId": self.room_id,
                "from": origin,
                "moves": moves,
                "state": state,
            },
        )

    async def broadcast_clock(self) -> None:
        await self._broadcast({
            "type": "clock",
            "roomId": self.room_id,
            "clock": self.clock_payload(update=False),
        })

    async def handle_move(
        self, user_id: int, origin: str, target: str, promotion: Optional[str]
    ) -> None:
        async with self.lock:
            if self.status != "active":
                raise ValueError("Game is not active.")
            color = self.color_for(user_id)
            if color is None:
                raise ValueError("Player is not part of this game.")
            if color != self.game.turn:
                raise ValueError("Not your turn.")
            try:
                state = self.game.move(origin, target, promotion=promotion)
            except InvalidMoveError as exc:
                raise ValueError(str(exc)) from exc
            self.clock.on_move(color)

        uci = move_to_uci(origin, target, promotion)
        await asyncio.to_thread(append_move, self.game_id, uci)
        await self.broadcast_state()

        if state.get("status") != "active":
            await self.end_game(state.get("status", "finished"), state.get("winner"), "game_end")

    async def handle_resign(self, user_id: int) -> None:
        color = self.color_for(user_id)
        if color is None:
            return
        await self.end_game("resign", opponent(color), "resign")

    async def handle_disconnect(self, user_id: int) -> None:
        await self.detach_connection(user_id)
        async with self.lock:
            if self.status != "active":
                return
            if user_id in self.disconnect_tasks:
                return
            self.disconnect_tasks[user_id] = asyncio.create_task(
                self._disconnect_grace(user_id)
            )
        opponent_info = self.opponent_for(user_id)
        await self._safe_send(
            opponent_info.user_id,
            {
                "type": "opponent_left",
                "roomId": self.room_id,
                "graceSec": DISCONNECT_GRACE_SEC,
            },
        )

    async def end_game(self, status: str, winner: Optional[str], reason: str) -> None:
        async with self.lock:
            if self.status != "active":
                return
            self.status = status
            self.winner = winner
            self.clock.pause()
            if self.clock_task:
                self.clock_task.cancel()
            end_state = self._decorate_state(self.game.state())
            end_state["status"] = status
            end_state["winner"] = winner
            end_state["winnerLabel"] = (
                "Albe" if winner == WHITE else "Negre" if winner == BLACK else None
            )
            payload = {
                "type": "game_over",
                "roomId": self.room_id,
                "status": status,
                "winner": winner,
                "reason": reason,
                "state": end_state,
                "clock": self.clock_payload(update=False),
            }
        await asyncio.to_thread(set_game_result, self.game_id, status, winner)
        await self._broadcast(payload)
        if self.on_end:
            await self.on_end(self)

    async def _clock_loop(self) -> None:
        while True:
            await asyncio.sleep(CLOCK_TICK_SEC)
            async with self.lock:
                if self.status != "active":
                    return
                flagged = self.clock.tick()
                clock_payload = self.clock_payload(update=False)
            if flagged:
                await self.end_game("timeout", opponent(flagged), "timeout")
                return
            await self._broadcast({
                "type": "clock",
                "roomId": self.room_id,
                "clock": clock_payload,
            })

    async def _disconnect_grace(self, user_id: int) -> None:
        await asyncio.sleep(DISCONNECT_GRACE_SEC)
        async with self.lock:
            if self.status != "active":
                return
            if user_id in self.connections:
                return
        color = self.color_for(user_id)
        if color is None:
            return
        await self.end_game("abandoned", opponent(color), "disconnect")

    async def _safe_send(self, user_id: int, payload: dict[str, Any]) -> None:
        websocket = self.connections.get(user_id)
        if websocket is None:
            return
        try:
            await websocket.send_json(payload)
        except Exception:
            await self.detach_connection(user_id)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        for user_id in list(self.connections.keys()):
            await self._safe_send(user_id, payload)

    def _match_payload(self, user_id: int) -> dict[str, Any]:
        player = self.white if user_id == self.white.user_id else self.black
        opponent_info = self.opponent_for(user_id)
        return {
            "type": "match_found",
            "roomId": self.room_id,
            "color": player.color,
            "opponent": self._player_payload(opponent_info),
            "timeControl": {
                "baseMin": self.base_min,
                "incrementSec": self.increment_sec,
            },
            "state": self._decorate_state(self.game.state()),
            "clock": self.clock_payload(update=False),
        }

    def _reconnect_payload(self, user_id: int) -> dict[str, Any]:
        player = self.white if user_id == self.white.user_id else self.black
        opponent_info = self.opponent_for(user_id)
        return {
            "type": "reconnected",
            "roomId": self.room_id,
            "color": player.color,
            "opponent": self._player_payload(opponent_info),
            "timeControl": {
                "baseMin": self.base_min,
                "incrementSec": self.increment_sec,
            },
            "state": self._decorate_state(self.game.state()),
            "clock": self.clock_payload(update=False),
        }

    def _state_payload(self) -> dict[str, Any]:
        return {
            "type": "state",
            "roomId": self.room_id,
            "state": self._decorate_state(self.game.state()),
            "clock": self.clock_payload(update=False),
        }


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._user_to_room: dict[int, str] = {}
        self._lock = asyncio.Lock()

    async def create_room(
        self,
        entry_a: Any,
        entry_b: Any,
        base_min: int,
        increment_sec: int,
    ) -> Room:
        color_pick = random.choice([WHITE, BLACK])
        if color_pick == WHITE:
            white_entry, black_entry = entry_a, entry_b
        else:
            white_entry, black_entry = entry_b, entry_a

        room_id = str(uuid.uuid4())
        game_id = await asyncio.to_thread(
            create_game_record,
            white_entry.user["id"],
            black_entry.user["id"],
            room_id,
            base_min,
            increment_sec,
        )

        room = Room(
            room_id=room_id,
            white=PlayerInfo(
                user_id=white_entry.user["id"],
                username=white_entry.user["username"],
                rating=white_entry.user.get("rating"),
                color=WHITE,
            ),
            black=PlayerInfo(
                user_id=black_entry.user["id"],
                username=black_entry.user["username"],
                rating=black_entry.user.get("rating"),
                color=BLACK,
            ),
            base_min=base_min,
            increment_sec=increment_sec,
            game_id=game_id,
        )
        room.on_end = self._on_room_end

        async with self._lock:
            self._rooms[room_id] = room
            self._user_to_room[room.white.user_id] = room_id
            self._user_to_room[room.black.user_id] = room_id

        await room.attach_connection(room.white.user_id, white_entry.websocket)
        await room.attach_connection(room.black.user_id, black_entry.websocket)
        await room.start()
        return room

    async def get_room_for_user(self, user_id: int) -> Optional[Room]:
        async with self._lock:
            room_id = self._user_to_room.get(user_id)
            if not room_id:
                return None
            return self._rooms.get(room_id)

    async def attach_if_active(self, user_id: int, websocket: WebSocket) -> Optional[Room]:
        room = await self.get_room_for_user(user_id)
        if not room:
            return None
        await room.attach_connection(user_id, websocket)
        return room

    async def _on_room_end(self, room: Room) -> None:
        async with self._lock:
            self._rooms.pop(room.room_id, None)
            self._user_to_room.pop(room.white.user_id, None)
            self._user_to_room.pop(room.black.user_id, None)
