import os
from typing import Any, Dict, List, Optional

import asyncpg


_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> Optional[asyncpg.Pool]:
    global _pool

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None

    normalized_url = database_url.replace("postgresql+asyncpg://", "postgresql://")

    if _pool is None:
        _pool = await asyncpg.create_pool(normalized_url)

    return _pool


async def fetch(query: str, *args: Any) -> Optional[List[Dict[str, Any]]]:
    pool = await get_pool()
    if pool is None:
        return None

    async with pool.acquire() as connection:
        rows = await connection.fetch(query, *args)
        return [dict(row) for row in rows]


async def fetchrow(query: str, *args: Any) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    if pool is None:
        return None

    async with pool.acquire() as connection:
        row = await connection.fetchrow(query, *args)
        return dict(row) if row is not None else None


async def execute(query: str, *args: Any) -> Optional[str]:
    pool = await get_pool()
    if pool is None:
        return None

    async with pool.acquire() as connection:
        return await connection.execute(query, *args)
