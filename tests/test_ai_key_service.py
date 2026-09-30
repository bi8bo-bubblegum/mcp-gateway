"""AiKeyService 测试：热路径 verify / 缓存失效 / 管理写入。

按计划先写失败测试，再补最少实现。建 Key 一律直接插库（create 属于 2.2），
以便把"鉴权热路径"与"写入逻辑"两个关注点分开测。
"""
import secrets
from datetime import datetime

import pytest
from sqlalchemy import delete, select

from app.core.security import TokenHasher, token_display_prefix
from app.db.base import utcnow
from app.db.models import (
    AI_KEY_PERIOD_DAY,
    AI_KEY_PERIOD_NONE,
    AiApiKey,
    AiKeyModel,
)
from app.schemas.ai import AiKeyCreate, AiKeyPolicyUpdate
from app.services.ai_key_service import AiKeyService, AiKeySnapshot
from app.services.revision import RevisionStore, bump_revision


def _make_service(settings: "object") -> AiKeyService:
    return AiKeyService(
        settings=settings,  # type: ignore[arg-type]
        hasher=TokenHasher(settings.secret_key),  # type: ignore[attr-defined]
        revisions=RevisionStore(settings.revision_cache_ttl),  # type: ignore[attr-defined]
    )


async def _insert_key(settings, session, raw, *, enabled=True, revoked_at=None,
                       model_ids=None, **overrides):
    """直接落库一条 AI Key，绕开服务层（create 属 2.2）。"""
    hasher = TokenHasher(settings.secret_key)  # type: ignore[attr-defined]
    key = AiApiKey(
        name=overrides.pop("name", "key1"),
        key_hash=hasher.hash_token(raw),
        key_prefix=token_display_prefix(raw),
        enabled=enabled,
        revoked_at=revoked_at,
        period=overrides.pop("period", AI_KEY_PERIOD_NONE),
        period_token_limit=overrides.pop("period_token_limit", None),
        rate_limit_rpm=overrides.pop("rate_limit_rpm", None),
        owner=overrides.pop("owner", None),
        **overrides,
    )
    session.add(key)
    await session.flush()
    for mid in (model_ids or []):
        session.add(AiKeyModel(key_id=key.id, model_id=mid))
    await session.commit()
    return key


# ── 2.1 热路径 ─────────────────────────────────────────────────────

async def test_verify_returns_snapshot(db, settings):
    service = _make_service(settings)
    raw = "ai_" + secrets.token_urlsafe(16)
    async with db() as session:
        await _insert_key(
            settings, session, raw,
            name="mykey", model_ids=[1, 2],
            period=AI_KEY_PERIOD_DAY, period_token_limit=100, rate_limit_rpm=5,
        )
    snap = await service.verify(raw)
    assert isinstance(snap, AiKeySnapshot)
    assert snap.name == "mykey"
    assert snap.allowed_model_ids == frozenset({1, 2})
    assert snap.period == AI_KEY_PERIOD_DAY
    assert snap.period_token_limit == 100
    assert snap.rate_limit_rpm == 5


async def test_verify_rejects_revoked(db, settings):
    service = _make_service(settings)
    raw = "ai_" + secrets.token_urlsafe(16)
    async with db() as session:
        await _insert_key(settings, session, raw, revoked_at=utcnow())
    assert await service.verify(raw) is None


async def test_verify_rejects_disabled(db, settings):
    service = _make_service(settings)
    raw = "ai_" + secrets.token_urlsafe(16)
    async with db() as session:
        await _insert_key(settings, session, raw, enabled=False)
    assert await service.verify(raw) is None


async def test_snapshot_cached_until_revision_changes(db, settings):
    service = _make_service(settings)
    raw = "ai_" + secrets.token_urlsafe(16)
    async with db() as session:
        key = await _insert_key(settings, session, raw, model_ids=[1])
        key_id = key.id
    # 连续两次 verify 应命中同一份缓存对象（不重新查库）
    s1 = await service.verify(raw)
    s2 = await service.verify(raw)
    assert s1 is s2
    # 改策略：替换授权模型 + bump revision，再让本地缓存失效
    async with db() as session:
        await session.execute(delete(AiKeyModel).where(AiKeyModel.key_id == key_id))
        session.add(AiKeyModel(key_id=key_id, model_id=2))
        await bump_revision(session)
        await session.commit()
    service.invalidate()
    s3 = await service.verify(raw)
    assert s3 is not s1
    assert s3.allowed_model_ids == frozenset({2})


# ── 2.2 管理写入 ──────────────────────────────────────────────────

async def test_create_returns_plaintext_once(db, settings):
    service = _make_service(settings)
    async with db() as session:
        key, raw = await service.create(
            session, AiKeyCreate(name="fresh", model_ids=[1])
        )
    # 明文只在返回值里出现一次，且以 ai_ 前缀
    assert raw.startswith("ai_")
    assert len(raw) > len("ai_")
    async with db() as session:
        stored = await session.get(AiApiKey, key.id)
        # 库里只有哈希，没有明文；前缀就是明文前 12 字符
        assert stored.key_hash == TokenHasher(settings.secret_key).hash_token(raw)
        assert stored.key_prefix == token_display_prefix(raw)
        assert stored.key_hash != raw


async def test_update_policy_replaces_models(db, settings):
    service = _make_service(settings)
    async with db() as session:
        key, raw = await service.create(
            session, AiKeyCreate(name="p", model_ids=[1, 2])
        )
    async with db() as session:
        await service.update_policy(
            session, key.id, AiKeyPolicyUpdate(model_ids=[2, 3])
        )
    async with db() as session:
        result = await session.execute(
            select(AiKeyModel.model_id).where(AiKeyModel.key_id == key.id)
        )
        ids = {int(x) for x in result.scalars()}
    assert ids == {2, 3}
    # 更新后本地缓存已失效，verify 应看到新授权（全删全插而非累加）
    snap = await service.verify(raw)
    assert snap.allowed_model_ids == frozenset({2, 3})


async def test_revoke_sets_revoked_at(db, settings):
    service = _make_service(settings)
    async with db() as session:
        key, raw = await service.create(
            session, AiKeyCreate(name="r", model_ids=[1])
        )
    async with db() as session:
        revoked = await service.revoke(session, key.id)
        assert isinstance(revoked.revoked_at, datetime)
    # 撤销后立即 401（verify 返回 None，缓存已失效）
    assert await service.verify(raw) is None
