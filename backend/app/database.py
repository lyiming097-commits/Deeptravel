from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.config import Settings, get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL 未配置")
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"timeout": settings.database_connect_timeout_seconds},
    )


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    async with factory() as session, session.begin():
        yield session


async def database_health(settings: Settings) -> dict[str, str | bool | None]:
    if not settings.database_url:
        return {"configured": False, "connected": False, "pgvector_version": None}
    try:
        async with get_engine().connect() as connection:
            database = await connection.scalar(text("SELECT current_database()"))
            vector_version = await connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
        return {
            "configured": True,
            "connected": True,
            "database": str(database),
            "pgvector_version": str(vector_version) if vector_version else None,
        }
    except (SQLAlchemyError, OSError, RuntimeError) as exc:
        return {
            "configured": True,
            "connected": False,
            "pgvector_version": None,
            "error": exc.__class__.__name__,
        }
