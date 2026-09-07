"""Process-local maintenance exclusion and draining of mutating operations."""

from __future__ import annotations

import threading
import time
from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from app.core.logging import get_logger

logger = get_logger(__name__)


# ponytail: process-wide gate, single-process/single-worker only. A
# multi-worker deployment needs a DB-backed lock instead of this in-memory
# Event — not built here.
_restore_gate = threading.Event()

_RESTORE_DRAIN_TIMEOUT_S = 30.0

backup_operation_lock = threading.RLock()

_mutation_condition = threading.Condition()

_active_mutations = 0

_P = ParamSpec("_P")

_R = TypeVar("_R")


class RestoreConflictError(Exception):
    """Raised when a restore is refused because ingestion work is in flight."""


def restore_in_progress() -> bool:
    return _restore_gate.is_set()


def begin_mutating_operation() -> bool:
    """Register a write-capable operation unless restore maintenance is active."""
    global _active_mutations
    with _mutation_condition:
        if _restore_gate.is_set():
            return False
        _active_mutations += 1
        return True


def end_mutating_operation() -> None:
    global _active_mutations
    with _mutation_condition:
        if _active_mutations <= 0:
            raise RuntimeError("unbalanced_mutating_operation")
        _active_mutations -= 1
        if _active_mutations == 0:
            _mutation_condition.notify_all()


def begin_restore_maintenance() -> None:
    """Block new mutations and wait for already-admitted ones to drain."""
    deadline = time.monotonic() + _RESTORE_DRAIN_TIMEOUT_S
    with _mutation_condition:
        _restore_gate.set()
        while _active_mutations:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _restore_gate.clear()
                _mutation_condition.notify_all()
                raise RestoreConflictError(
                    f"{_active_mutations} write operation(s) still active; retry later"
                )
            _mutation_condition.wait(timeout=remaining)


def end_restore_maintenance() -> None:
    with _mutation_condition:
        _restore_gate.clear()
        _mutation_condition.notify_all()


def exclusive_backup_operation(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Prevent overlapping backup/restore operations in this process."""

    @wraps(func)
    def serialized(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with backup_operation_lock:
            return func(*args, **kwargs)

    return serialized


def hold_restore_maintenance() -> None:
    """Keep mutations gated while durable recovery evidence remains unresolved."""
    with _mutation_condition:
        _restore_gate.set()
