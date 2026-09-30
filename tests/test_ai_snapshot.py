"""AiRuntimeRegistry / AiModelDescriptor 测试：alias → model → provider 解析。

仿 app/gateway/runtime.py 的快照注册表：revision + asyncio.Lock 双检重建，
只收 enabled 供应商 × enabled 模型，供应商密钥用 SecretBox 解密。
"""
import pytest
from sqlalchemy import select

from app.ai.snapshot import AiModelDescriptor, AiRuntimeRegistry
from app.core.security import SecretBox
from app.db.models import (
    AI_MODEL_KIND_CHAT,
    AiModel,
    AiProvider,
)
from app.services.revision import RevisionStore


def _make_registry(settings) -> AiRuntimeRegistry:
    return AiRuntimeRegistry(
        settings=settings,
        revisions=RevisionStore(settings.revision_cache_ttl),
        secret_box=SecretBox(settings.secret_key),
    )


async def _insert_provider(settings, session, *, slug="openai", enabled=True,
                           base_url="https://api.openai.com/v1", **kw):
    prov = AiProvider(
        slug=slug,
        name=kw.pop("name", slug),
        base_url=base_url,
        enabled=enabled,
        api_key_ciphertext=kw.pop("api_key_ciphertext", None),
        **kw,
    )
    session.add(prov)
    await session.flush()
    return prov


async def _insert_model(session, provider_id, *, alias="gpt", provider_model_name="gpt-4o",
                        enabled=True, kind=AI_MODEL_KIND_CHAT):
    m = AiModel(
        provider_id=provider_id,
        provider_model_name=provider_model_name,
        alias=alias,
        kind=kind,
        enabled=enabled,
    )
    session.add(m)
    await session.commit()
    return m


async def test_resolve_returns_model_and_provider(db, settings):
    registry = _make_registry(settings)
    async with db() as session:
        prov = await _insert_provider(settings, session, slug="oa", base_url="https://oa/v1")
        await _insert_model(session, prov.id, alias="gpt", provider_model_name="gpt-4o")
    await registry.snapshot()
    d = registry.resolve("gpt")
    assert isinstance(d, AiModelDescriptor)
    assert d.model_id
    assert d.alias == "gpt"
    assert d.provider_slug == "oa"
    assert d.provider_model_name == "gpt-4o"
    assert d.kind == AI_MODEL_KIND_CHAT
    assert d.base_url == "https://oa/v1"
    assert d.provider_id == prov.id


async def test_resolve_rejects_disabled_model(db, settings):
    registry = _make_registry(settings)
    async with db() as session:
        prov = await _insert_provider(settings, session)
        await _insert_model(session, prov.id, alias="gpt", enabled=False)
    await registry.snapshot()
    assert registry.resolve("gpt") is None


async def test_resolve_rejects_disabled_provider(db, settings):
    registry = _make_registry(settings)
    async with db() as session:
        prov = await _insert_provider(settings, session, enabled=False)
        await _insert_model(session, prov.id, alias="gpt")
    await registry.snapshot()
    assert registry.resolve("gpt") is None


async def test_snapshot_rebuilt_after_revision_bump(db, settings):
    registry = _make_registry(settings)
    async with db() as session:
        prov = await _insert_provider(settings, session)
        await _insert_model(session, prov.id, alias="gpt")
    await registry.snapshot()
    assert registry.resolve("gpt") is not None
    # 停用模型 + bump revision + 失效缓存，重建后该别名应消失
    async with db() as session:
        model = (await session.execute(
            select(AiModel).where(AiModel.alias == "gpt")
        )).scalar_one()
        model.enabled = False
        await session.commit()
    from app.services.revision import bump_revision
    async with db() as session:
        await bump_revision(session)
    registry.invalidate()
    await registry.snapshot()
    assert registry.resolve("gpt") is None
