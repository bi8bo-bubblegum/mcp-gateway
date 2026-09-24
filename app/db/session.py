from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

def init_engine(database_url: str, *, echo: bool = False) -> None:
    global _engine, _session_factory
    _engine = create_async_engine(database_url, echo=echo, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)

async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None

def engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError('数据库引擎未初始化')
    return _engine

def session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError('数据库引擎未初始化')
    return _session_factory

@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise

async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session