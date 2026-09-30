"""AI Key 服务：热路径鉴权 + 管理写入。

设计文档 §4.1① 与 §3.3/§3.4。仿 TokenService 的"双键缓存 + revision/TTL
双条件失效 + KeyedLocks single-flight"模式：明文只在 create 返回一次，库里
只存 HMAC 哈希；allowed_model_ids 来自 ai_key_models（deny-by-default）。

verify 的失效条件：revision 变化（写操作 bump_revision）或超过 ai_key_cache_ttl。
本地写操作后调用 invalidate() 清掉本进程缓存，跨进程靠 revision 广播在 TTL 内最终一致。
"""
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import KeyedLocks
from app.core.config import Settings
from app.core.security import TokenHasher
from app.db.base import utcnow
from app.db.models import (
    AI_KEY_PERIOD_NONE,
    AiApiKey,
    AiKeyModel,
)
from app.db.session import session_scope
from app.schemas.ai import AiKeyCreate, AiKeyPolicyUpdate
from app.services.revision import RevisionStore, bump_revision


class AiKeyServiceError(Exception):
    """Key 策略不一致或不存在时抛出。"""


@dataclass(frozen=True)
class AiKeySnapshot:
    """请求热路径用的不可变策略视图。"""

    id: int
    name: str
    allowed_model_ids: frozenset[int]
    period: str
    period_token_limit: int | None
    rate_limit_rpm: int | None


@dataclass
class _CacheEntry:
    snapshot: AiKeySnapshot
    revision: int
    expires_at: float


class AiKeyService:
    def __init__(
        self, *, settings: Settings, hasher: TokenHasher, revisions: RevisionStore
    ) -> None:
        self._settings = settings
        self._hasher = hasher
        self._revisions = revisions
        self._by_hash: dict[str, _CacheEntry] = {}
        self._by_id: dict[int, _CacheEntry] = {}
        self._locks = KeyedLocks()

    # -------------------------------------------------------- 热路径鉴权

    async def verify(self, raw: str) -> AiKeySnapshot | None:
        """把明文 Key 解析成策略快照，无效/停用/撤销返回 None。

        命中缓存直接返回；未命中加锁后复查一次，避免 revision 失效瞬间同 token
        的并发请求各自回源查库（一次 verify = 1 条 key + 1 条授权查询）。
        """
        if not raw:
            return None
        key_hash = self._hasher.hash_token(raw)
        revision = await self._revisions.current()
        cached = self._by_hash.get(key_hash)
        if cached is not None and self._fresh(cached, revision):
            return cached.snapshot

        async with self._locks.hold(f"hash:{key_hash}"):
            revision = await self._revisions.current()
            cached = self._by_hash.get(key_hash)
            if cached is not None and self._fresh(cached, revision):
                return cached.snapshot  # 等锁期间已被其他协程填好

            async with session_scope() as session:
                row = (
                    await session.execute(
                        select(AiApiKey).where(AiApiKey.key_hash == key_hash)
                    )
                ).scalar_one_or_none()
                if row is None or not row.enabled or row.revoked_at is not None:
                    self._by_hash.pop(key_hash, None)
                    return None
                snapshot = await self._build_snapshot(session, row)

            entry = _CacheEntry(
                snapshot=snapshot,
                revision=revision,
                expires_at=time.monotonic() + self._settings.ai_key_cache_ttl,
            )
            self._by_hash[key_hash] = entry
            self._by_id[snapshot.id] = entry
            return snapshot

    async def snapshot_by_id(self, key_id: int) -> AiKeySnapshot | None:
        """按 id 取快照（路由层在鉴权后可能再次用到，复用同一套缓存）。"""
        revision = await self._revisions.current()
        cached = self._by_id.get(key_id)
        if cached is not None and self._fresh(cached, revision):
            return cached.snapshot

        async with self._locks.hold(f"id:{key_id}"):
            revision = await self._revisions.current()
            cached = self._by_id.get(key_id)
            if cached is not None and self._fresh(cached, revision):
                return cached.snapshot

            async with session_scope() as session:
                row = await session.get(AiApiKey, key_id)
                if row is None or not row.enabled or row.revoked_at is not None:
                    self._by_id.pop(key_id, None)
                    return None
                snapshot = await self._build_snapshot(session, row)

            entry = _CacheEntry(
                snapshot=snapshot,
                revision=revision,
                expires_at=time.monotonic() + self._settings.ai_key_cache_ttl,
            )
            self._by_id[key_id] = entry
            return snapshot

    def _fresh(self, entry: _CacheEntry, revision: int) -> bool:
        # revision 变化（配置被改）或 TTL 到期都视为过期，必须回源
        return entry.revision == revision and entry.expires_at > time.monotonic()

    def invalidate(self, key_id: int | None = None) -> None:
        """写操作后清掉本进程缓存；key_id 省略则全清。

        不碰 RevisionStore：跨进程的失效靠 revision 广播；本进程刚发生写操作，
        清掉本地 key 缓存后下一次 verify 会回源，自然拿到新数据。
        """
        if key_id is None:
            self._by_hash.clear()
            self._by_id.clear()
            return
        self._by_id.pop(key_id, None)
        for h, entry in list(self._by_hash.items()):
            if entry.snapshot.id == key_id:
                del self._by_hash[h]

    async def _build_snapshot(
        self, session: AsyncSession, row: AiApiKey
    ) -> AiKeySnapshot:
        result = await session.execute(
            select(AiKeyModel.model_id).where(AiKeyModel.key_id == row.id)
        )
        allowed = frozenset(int(m) for m in result.scalars())
        return AiKeySnapshot(
            id=row.id,
            name=row.name,
            allowed_model_ids=allowed,
            period=row.period,
            period_token_limit=row.period_token_limit,
            rate_limit_rpm=row.rate_limit_rpm,
        )

    # ----------------------------------------------------------- 管理写入

    async def create(
        self, session: AsyncSession, payload: AiKeyCreate
    ) -> tuple[AiApiKey, str]:
        """新建 Key：明文只在此处返回一次，库里只存哈希。"""
        from app.core.security import generate_ai_key

        raw = generate_ai_key()
        key = AiApiKey(
            name=payload.name,
            key_hash=self._hasher.hash_token(raw),
            key_prefix=_display_prefix(raw),
            owner=payload.owner,
            enabled=True,
            period_token_limit=payload.period_token_limit,
            period=payload.period,
            rate_limit_rpm=payload.rate_limit_rpm,
        )
        session.add(key)
        await session.flush()
        for mid in payload.model_ids:
            session.add(AiKeyModel(key_id=key.id, model_id=mid))
        # 任何写操作都 bump revision，让跨进程缓存失效
        await bump_revision(session)
        await session.commit()
        self.invalidate()
        return key, raw

    async def update_policy(
        self, session: AsyncSession, key_id: int, payload: AiKeyPolicyUpdate
    ) -> AiApiKey:
        key = await self._require_key(session, key_id)
        if payload.name is not None:
            key.name = payload.name
        if payload.enabled is not None:
            key.enabled = payload.enabled
        if payload.period_token_limit is not None:
            key.period_token_limit = payload.period_token_limit
        if payload.period is not None:
            key.period = payload.period
        if payload.rate_limit_rpm is not None:
            key.rate_limit_rpm = payload.rate_limit_rpm
        # 授权模型全删全插：提供即整体替换，不提供则保持原状
        if payload.model_ids is not None:
            await session.execute(
                delete(AiKeyModel).where(AiKeyModel.key_id == key_id)
            )
            await session.flush()
            for mid in payload.model_ids:
                session.add(AiKeyModel(key_id=key_id, model_id=mid))
        await bump_revision(session)
        await session.commit()
        self.invalidate(key_id)
        await session.refresh(key)
        return key

    async def revoke(self, session: AsyncSession, key_id: int) -> AiApiKey:
        key = await self._require_key(session, key_id)
        key.enabled = False
        key.revoked_at = utcnow()
        await bump_revision(session)
        await session.commit()
        self.invalidate(key_id)
        await session.refresh(key)
        return key

    async def _require_key(self, session: AsyncSession, key_id: int) -> AiApiKey:
        key = await session.get(AiApiKey, key_id)
        if key is None:
            raise AiKeyServiceError(f"AI Key {key_id} 不存在")
        return key


def _display_prefix(raw: str) -> str:
    # 复用现有 token 前缀取法，保证与 AiKeyRead.key_prefix 一致
    from app.core.security import token_display_prefix

    return token_display_prefix(raw)
