from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

def init_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_size: int = 20,
    max_overflow: int = 20,
    pool_timeout: float = 10.0,
    pool_recycle: int = 1800,
) -> None:
    """建全局引擎。

    连接池默认值必须是显式的：SQLAlchemy 的默认 5+10=15 条连接对 Web 服务勉强
    够用，但网关每个工具调用要在关键路径上写两次审计（start + complete），
    拿不到连接就会抛 AuditWriteError 进而拒绝调用，池子偏小会直接变成业务失败。

    pool_timeout 从默认的 30 秒收到 10 秒：审计写入本身是一条极快的语句，
    10 秒还拿不到连接说明数据库已经出问题了，再等 30 秒只会把延迟放大、占着
    请求处理器不放。

    pool_recycle 默认 -1（不回收），而 MySQL 的 wait_timeout 默认 8 小时会单方面
    掐掉空闲连接。虽然开了 pool_pre_ping，主动回收掉旧连接比每次 checkout 都靠
    探活发现更省一次往返。
    """
    global _engine, _session_factory
    options: dict[str, Any] = {"echo": echo, "pool_pre_ping": True}
    if not database_url.startswith("sqlite"):
        # SQLite（内存库用 StaticPool/SingletonThreadPool）不接受 QueuePool 参数
        options.update(
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
        )
    _engine = create_async_engine(database_url, **options)
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