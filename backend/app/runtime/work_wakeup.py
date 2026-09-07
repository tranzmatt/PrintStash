"""Local scheduler notifications; accepted work lives in the database.

This is not a durable queue and makes no lease or delivery guarantees. The
scheduler drains persisted work and uses notices only to shorten its next poll.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class WorkNotice:
    job_id: str
    kind: str
    payload: dict[str, Any]


@runtime_checkable
class WorkWakeup(Protocol):
    async def notify(self, task: WorkNotice) -> None: ...

    async def wait(self) -> WorkNotice: ...


class LocalWorkWakeup:
    """Local-first task transport; persistence lives in JobRegistry repository."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[WorkNotice] = asyncio.Queue()

    async def notify(self, task: WorkNotice) -> None:
        await self._queue.put(task)

    async def wait(self) -> WorkNotice:
        return await self._queue.get()
