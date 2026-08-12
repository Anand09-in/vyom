"""GET /health — liveness probe."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from vyom.api.deps import get_repo

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(repo=Depends(get_repo)):
    try:
        async with repo._pool.connection() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok", "db": "ok"}
    except Exception as exc:
        return {"status": "degraded", "db": str(exc)}