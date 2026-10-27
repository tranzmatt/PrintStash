"""Bounded local model hints. No inputs, credentials or durable tasks live here."""

import re
import threading
from collections import OrderedDict


class WarmupRequests:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: OrderedDict[str, None] = OrderedDict()
        # Set by a request or a stop: an idle warm-up waits on it instead of
        # reading the settings on a short clock.
        self._wake = threading.Event()

    def request(self, identity: str):
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("embedding_model_identity_invalid")
        with self._lock:
            self._pending[identity] = None
            self._pending.move_to_end(identity)
            while len(self._pending) > 4:
                self._pending.popitem(last=False)
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def wait(self, seconds: float) -> bool:
        """Sleep until a request or wake, at most ``seconds``; True when woken."""
        woken = self._wake.wait(seconds)
        self._wake.clear()
        return woken

    def take(self) -> str | None:
        with self._lock:
            return self._pending.popitem(last=False)[0] if self._pending else None

    def clear(self):
        with self._lock:
            self._pending.clear()


requests = WarmupRequests()
