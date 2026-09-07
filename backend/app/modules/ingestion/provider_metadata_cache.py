"""Provider metadata cache."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta

from app.modules.ingestion.capture_provider_connections import ProviderModelMetadata

_provider_metadata_cache: OrderedDict[
    tuple[int, str, str], tuple[ProviderModelMetadata, datetime]
] = OrderedDict()


_PROVIDER_CACHE_MAX = 256


_PROVIDER_CACHE_TTL = timedelta(minutes=5)


def invalidate_provider_metadata_cache(owner_user_id: int, provider: str) -> None:
    """Drop all cached metadata for one user's provider connection."""
    for key in tuple(_provider_metadata_cache):
        if key[0] == owner_user_id and key[1] == provider:
            _provider_metadata_cache.pop(key, None)
