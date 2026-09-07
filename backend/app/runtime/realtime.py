"""Best-effort local event publication, independent from HTTP connections.

Consumers subscribe an async message sink. The HTTP adapter supplies its socket
sender; other consumers can subscribe without constructing a WebSocket. A slow
or failed sink is dropped after the existing bounded send timeout.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Dict, Protocol, Set

from app.core.logging import get_logger

logger = get_logger(__name__)

MessageSink = Callable[[Dict[str, Any]], Awaitable[None]]

_SEND_TIMEOUT_S = 2.0


class EventPublisher(Protocol):
    async def publish(self, channel: str, payload: Dict[str, Any]) -> None: ...


class RealtimeBus(EventPublisher, Protocol):
    async def subscribe(self, channel: str, ws: MessageSink) -> None: ...

    async def unsubscribe(self, channel: str, ws: MessageSink) -> None: ...


class InProcessBus:
    """Single-process fan-out. Subscriber sends run concurrently so one slow
    or dead socket can't delay delivery to the rest of a channel."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[MessageSink]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, channel: str, ws: MessageSink) -> None:
        async with self._lock:
            self._subscribers.setdefault(channel, set()).add(ws)

    async def unsubscribe(self, channel: str, ws: MessageSink) -> None:
        async with self._lock:
            subs = self._subscribers.get(channel)
            if subs and ws in subs:
                subs.remove(ws)

    async def publish(self, channel: str, payload: Dict[str, Any]) -> None:
        async with self._lock:
            subs = list(self._subscribers.get(channel, ()))
        if not subs:
            return

        async def _send(ws: MessageSink) -> MessageSink | None:
            try:
                async with asyncio.timeout(_SEND_TIMEOUT_S):
                    await ws(payload)
                return None
            except Exception:
                return ws

        results = await asyncio.gather(*(_send(ws) for ws in subs))
        dead = [r for r in results if r is not None]
        if dead:
            async with self._lock:
                for ws in dead:
                    self._subscribers.get(channel, set()).discard(ws)
