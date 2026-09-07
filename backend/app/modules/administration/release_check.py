"""Check the official GitHub release feed for a newer PrintStash version."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import httpx

GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/xiao-villamor/PrintStash/releases/latest"
)
_CACHE_TTL_SECONDS = 6 * 60 * 60
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = asyncio.Lock()


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.fullmatch(value.strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def is_newer_release(latest: str, current: str) -> bool:
    """Compare stable PrintStash release tags without accepting arbitrary input."""
    latest_parts = _version_tuple(latest)
    current_parts = _version_tuple(current)
    return bool(
        latest_parts is not None
        and current_parts is not None
        and latest_parts > current_parts
    )


def _unavailable(current_version: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "current_version": current_version,
        "latest_version": None,
        "update_available": False,
        "release_url": None,
        "published_at": None,
        "checked_at": datetime.now(UTC).isoformat(),
    }


async def _fetch_release_status(
    current_version: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=5.0,
            follow_redirects=True,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"PrintStash/{current_version}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        ) as client:
            response = await client.get(GITHUB_LATEST_RELEASE_URL)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return _unavailable(current_version)

    if not isinstance(payload, dict):
        return _unavailable(current_version)

    tag_name = payload.get("tag_name")
    release_url = payload.get("html_url")
    if not isinstance(tag_name, str) or _version_tuple(tag_name) is None:
        return _unavailable(current_version)

    latest_version = tag_name.removeprefix("v")
    update_available = is_newer_release(latest_version, current_version)
    published_at = payload.get("published_at")
    return {
        "status": "update_available" if update_available else "up_to_date",
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": update_available,
        "release_url": release_url if isinstance(release_url, str) else None,
        "published_at": published_at if isinstance(published_at, str) else None,
        "checked_at": datetime.now(UTC).isoformat(),
    }


async def get_release_status(
    current_version: str, *, force: bool = False
) -> dict[str, Any]:
    """Return cached release state; network failure never breaks Settings."""
    now = monotonic()
    cached = _cache.get(current_version)
    if not force and cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    async with _cache_lock:
        cached = _cache.get(current_version)
        if not force and cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        result = await _fetch_release_status(current_version)
        _cache[current_version] = (monotonic(), result)
        return result
