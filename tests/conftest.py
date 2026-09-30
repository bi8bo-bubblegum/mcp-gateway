import os

# 测试全程用 sqlite 内存库 + 固定密钥；放行不安全默认值，否则 import app.main
# 时模块级 build_app() 触发的配置校验会直接抛错（生产必须用真实密钥覆盖）。
os.environ.setdefault("GATEWAY_ALLOW_INSECURE_DEFAULTS", "true")

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.session import dispose_engine, engine, init_engine, session_factory
from app.main import build_app, build_container


@pytest.fixture
def settings() -> Settings:
    """测试专用配置：sqlite 内存库 + 固定密钥 + 极短超时。

    超时必须收紧：假上游的 timeout 模式会永久挂起，用默认的 120s 会让该用例
    真的等两分钟。1s 足够覆盖"客户端按超时失败"的断言。
    """
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        secret_key="test-key",
        allow_insecure_defaults=True,
        ai_request_timeout=1.0,
        ai_connect_timeout=0.5,
    )


@pytest.fixture
def upstream():
    """假 OpenAI 兼容上游实例（每测试全新一个，mode 默认 ok）。"""
    from tests.fakes.openai_upstream import make_upstream_app

    return make_upstream_app()


@pytest_asyncio.fixture
async def db(settings: Settings) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """建表并逐测试清理：每个测试用独立的全新 schema；yield 会话工厂供测试自开 session。"""
    init_engine(settings.database_url, echo=False)
    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield session_factory()
    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await dispose_engine()


class _CountingTransport(httpx.ASGITransport):
    """ASGI 上游 + 记录收到过的请求，供断言「护栏拦截时上游未被调用」。"""

    def __init__(self, app: object, calls: list) -> None:
        super().__init__(app=app)
        self._calls = calls

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._calls.append(request)
        return await super().handle_async_request(request)


@pytest.fixture
def upstream_calls() -> list:
    """假上游收到的请求列表（httpx.Request），由 client fixture 的 transport 写入。"""
    return []


@pytest_asyncio.fixture
async def client(db, settings: Settings, upstream, upstream_calls) -> AsyncIterator[AsyncClient]:
    """用可注入的 container 包出 ASGI 客户端，测试不触网（上游由假工厂替换）。

    AiUpstreamPool 的客户端工厂被替换成 httpx.ASGITransport(app=假上游)，让所有
    AI 请求都打到内存假上游，绝不触网；transport 额外记录请求，供断言上游是否被调用。

    必须依赖 db fixture：ASGITransport 不执行 lifespan，app 自身不会 init_engine，
    否则应用内 session_factory() 直接抛「数据库引擎未初始化」，且建表也会丢。
    """
    def fake_upstream_factory(base_url: str, api_key: str, settings: Settings) -> httpx.AsyncClient:
        # base_url 仅用于拼 URL；ASGITransport 忽略主机，直接把请求 dispatch 到假上游 app
        return httpx.AsyncClient(
            base_url=base_url,
            transport=_CountingTransport(upstream, upstream_calls),
        )

    container = build_container(settings, ai_client_factory=fake_upstream_factory)
    app = build_app(container)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def ai_seed(db, settings: Settings) -> AsyncIterator["_AiSeed"]:
    """造一份最小可用的 AI 网关数据：一个启用厂商 + 若干模型 + 一个 Key + 可选护栏。

    返回 raw Key 明文与模型 id 映射，供 e2e 测试直接拿去请求。base_url 用占位
    http://fake/v1，配合 client fixture 的假上游工厂即可不触网打到假上游。
    """
    from app.core.security import (
        SecretBox,
        TokenHasher,
        generate_ai_key,
        token_display_prefix,
    )
    from app.db.models import (
        AI_KEY_PERIOD_NONE,
        AI_MODEL_KIND_CHAT,
        AI_MODEL_KIND_EMBEDDING,
        GUARDRAIL_ACTION_BLOCK,
        GUARDRAIL_SCOPE_REQUEST,
        AiApiKey,
        AiKeyModel,
        AiModel,
        AiProvider,
        GuardrailRule,
    )

    secret_box = SecretBox(settings.secret_key)

    class _AiSeed:
        async def __call__(
            self,
            *,
            chat_alias: str = "gpt-4o-mini",
            embedding_alias: str = "text-embedding-3-small",
            base_url: str = "http://fake/v1",
            period: str = AI_KEY_PERIOD_NONE,
            quota: int | None = None,
            rpm: int | None = None,
            models: tuple[str, ...] = ("chat",),
            guardrails: list[dict] | None = None,
        ) -> dict:
            hasher = TokenHasher(settings.secret_key)
            raw = generate_ai_key()
            async with db() as session:
                prov = AiProvider(
                    slug="oa",
                    name="OpenAI",
                    base_url=base_url,
                    enabled=True,
                    api_key_ciphertext=secret_box.encrypt({"bearer_token": "sk-up"}),
                )
                session.add(prov)
                await session.flush()
                key = AiApiKey(
                    name="k",
                    key_hash=hasher.hash_token(raw),
                    key_prefix=token_display_prefix(raw),
                    enabled=True,
                    period=period,
                    period_token_limit=quota,
                    rate_limit_rpm=rpm,
                )
                session.add(key)
                await session.flush()
                model_ids: dict[str, int] = {}
                for kind in models:
                    alias = chat_alias if kind == AI_MODEL_KIND_CHAT else embedding_alias
                    m = AiModel(
                        provider_id=prov.id,
                        provider_model_name=alias,
                        alias=alias,
                        kind=kind,
                        enabled=True,
                    )
                    session.add(m)
                    await session.flush()
                    session.add(AiKeyModel(key_id=key.id, model_id=m.id))
                    model_ids[alias] = m.id
                if guardrails:
                    for g in guardrails:
                        session.add(
                            GuardrailRule(
                                name=g["name"],
                                pattern=g["pattern"],
                                scope=g.get("scope", GUARDRAIL_SCOPE_REQUEST),
                                action=GUARDRAIL_ACTION_BLOCK,
                                enabled=True,
                            )
                        )
                await session.commit()
            return {
                "raw": raw,
                "key_id": key.id,
                "model_ids": model_ids,
                "provider_id": prov.id,
            }

    yield _AiSeed()

