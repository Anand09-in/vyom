"""FastAPI dependency injection.

Pool, repo, and provider are created once per process and reused across
all requests. FastAPI's dependency system handles the lifecycle.
"""
from __future__ import annotations

from functools import lru_cache

from vyom.config import get_settings
from vyom.providers import get_provider
from vyom.providers.base import Provider
from vyom.store.history import HistoryStore
from vyom.store.repo import AsyncConnectionPool, Repository

# Module-level singletons — set during app startup lifespan
_pool: AsyncConnectionPool | None = None
_repo: Repository | None = None
_history_store: HistoryStore | None = None


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        from vyom.store.repo import create_pool
        _pool = await create_pool(get_settings())
        await _pool.open()
    return _pool


async def get_repo() -> Repository:
    global _repo
    if _repo is None:
        pool = await get_pool()
        _repo = Repository(pool)
    return _repo


@lru_cache
def get_provider_dep() -> Provider:
    """Cached provider — models are loaded once, not per request."""
    return get_provider()


def get_history_store() -> HistoryStore:
    global _history_store
    if _history_store is None:
        _history_store = HistoryStore(get_settings())
    return _history_store