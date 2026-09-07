"""Short-lived, one-use browser WebSocket authentication tickets."""

from __future__ import annotations

import secrets
import threading
import time

TTL_SECONDS = 30

_lock = threading.Lock()
_tickets: dict[str, tuple[int, int, float]] = {}


def issue(user_id: int, printer_id: int) -> str:
    ticket = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _lock:
        expired = [key for key, (_, _, expiry) in _tickets.items() if expiry <= now]
        for key in expired:
            _tickets.pop(key, None)
        _tickets[ticket] = (user_id, printer_id, now + TTL_SECONDS)
    return ticket


def consume(ticket: str, printer_id: int) -> int | None:
    with _lock:
        entry = _tickets.pop(ticket, None)
    if entry is None:
        return None
    user_id, expected_printer_id, expires_at = entry
    if expected_printer_id != printer_id or expires_at <= time.monotonic():
        return None
    return user_id
