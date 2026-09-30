import os

# 测试全程用 sqlite 内存库 + 固定密钥；放行不安全默认值，否则 import app.main
# 时模块级 build_app() 触发的配置校验会直接抛错（生产必须用真实密钥覆盖）。
os.environ.setdefault("GATEWAY_ALLOW_INSECURE_DEFAULTS", "true")

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.db.base import Base
from app.db.session import dispose_engine, engine, init_engine, session_factory
from app.main import build_app, build_container


@pytest.fixture
def settings() -> Settings:
    """测试专用配置：sqlite 内存库 + 固定密钥 + 放行不安全默认值。"""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        secret_key="test-key",
        allow_insecure_defaults=True,
    )


@pytest_asyncio.fixture
async def db(settings: Settings) -> AsyncIterator[AsyncIterator]:
    """建表并逐测试清理：每个测试用独立的全新 schema。"""
    init_engine(settings.database_url, echo=False)
    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_factory()
    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await dispose_engine()


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """用可注入的 container 包出 ASGI 客户端，测试不触网（上游由假工厂替换）。"""
    container = build_container(settings)
    app = build_app(container)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
