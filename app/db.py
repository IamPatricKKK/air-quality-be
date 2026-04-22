"""
Database connection layer.
Provides both:
  - asyncpg pool (legacy, for raw SQL queries)
  - SQLAlchemy async session (for ORM-based code)
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


# ─── Load .env ──────────────────────────────────────────────

def load_local_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()


def _get_database_url() -> Optional[str]:
    return os.getenv("DATABASE_URL")


def _get_async_url() -> Optional[str]:
    """Convert DATABASE_URL to async driver URL."""
    url = _get_database_url()
    if not url:
        return None
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+asyncpg://"):
        return url
    return f"postgresql+asyncpg://{url}"


# ─── asyncpg pool (legacy) ──────────────────────────────────

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> Optional[asyncpg.Pool]:
    global _pool
    database_url = _get_database_url()
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


# ─── SQLAlchemy async engine + session ──────────────────────

_engine = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine():
    global _engine
    if _engine is None:
        url = _get_async_url()
        if url:
            _engine = create_async_engine(url, pool_size=5, max_overflow=10, echo=False)
    return _engine


def get_session_factory() -> Optional[async_sessionmaker[AsyncSession]]:
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        if engine:
            _session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session():
    """Async context manager for SQLAlchemy session."""
    factory = get_session_factory()
    if factory is None:
        raise RuntimeError("DATABASE_URL not configured")
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_pool():
    """Cleanup on shutdown."""
    global _pool, _engine
    if _pool:
        await _pool.close()
        _pool = None
    if _engine:
        await _engine.dispose()
        _engine = None
