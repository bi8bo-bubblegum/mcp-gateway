"""AI 模型解析快照：alias → model → provider。

仿 app/gateway/runtime.py 的快照注册表模式：revision + asyncio.Lock 双检重建，
避免 revision 失效瞬间所有请求各自全表查询。只收 enabled 供应商 × enabled 模型；
供应商的上游密钥用 SecretBox 解密成 UpstreamAuth（解密失败的服务整体跳过）。

resolve(alias) 在 snapshot() 之后调用，返回不可变描述符；解析不到返回 None，
对应链路上的 404 model_not_found。
"""
import asyncio
import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from sqlalchemy import select

from app.core.config import Settings
from app.core.security import SecretBox
from app.db.models import (
    AI_MODEL_KIND_CHAT,
    AiModel,
    AiProvider,
)
from app.services.revision import RevisionStore
from app.services.upstream import UpstreamAuth, decrypt_auth

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AiModelDescriptor:
    """对外暴露一个 alias 的完整解析结果（含上游调用所需信息）。"""

    model_id: int
    alias: str
    provider_slug: str
    provider_model_name: str
    kind: str
    base_url: str
    # 上游鉴权：空 UpstreamAuth 表示厂商未配置密钥；绝不在日志里泄露具体值
    auth: UpstreamAuth
    provider_id: int
    input_price: float | None
    output_price: float | None


@dataclass(frozen=True)
class AiRegistrySnapshot:
    revision: int
    descriptors: Mapping[str, AiModelDescriptor]

    def resolve(self, alias: str) -> AiModelDescriptor | None:
        return self.descriptors.get(alias)


class AiRuntimeRegistry:
    def __init__(
        self, *, settings: Settings, revisions: RevisionStore, secret_box: SecretBox
    ) -> None:
        self._settings = settings
        self._revisions = revisions
        self._secret_box = secret_box
        self._snapshot: AiRegistrySnapshot | None = None
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        """配置变更后清掉缓存，迫使下次 snapshot() 重建。"""
        self._snapshot = None

    async def snapshot(self) -> AiRegistrySnapshot:
        revision = await self._revisions.current()
        cached = self._snapshot
        if cached is not None and cached.revision == revision:
            return cached
        # revision 变化后所有请求会同时到达这里，没有锁就是 N 份重复全表查询。
        # 锁内重新读一次 revision 并复查，避免排队者重复重建。
        async with self._lock:
            revision = await self._revisions.current()
            cached = self._snapshot
            if cached is not None and cached.revision == revision:
                return cached
            return await self._rebuild(revision)

    def resolve(self, alias: str) -> AiModelDescriptor | None:
        """必须在 snapshot() 之后调用；尚未构建快照时直接返回 None。"""
        if self._snapshot is None:
            return None
        return self._snapshot.descriptors.get(alias)

    async def _rebuild(self, revision: int) -> AiRegistrySnapshot:
        from app.db.session import session_scope

        async with session_scope() as session:
            provider_rows = list(
                (
                    await session.execute(
                        select(AiProvider).where(AiProvider.enabled.is_(True))
                    )
                ).scalars()
            )
            provider_ids = [p.id for p in provider_rows]
            model_rows: list[AiModel] = []
            if provider_ids:
                model_rows = list(
                    (
                        await session.execute(
                            select(AiModel).where(
                                AiModel.enabled.is_(True),
                                AiModel.provider_id.in_(provider_ids),
                            )
                        )
                    ).scalars()
                )

            # 解密上游密钥；失败的服务整体跳过，避免带坏凭证的模型被转发
            providers: dict[int, tuple[str, str, UpstreamAuth]] = {}
            for p in provider_rows:
                try:
                    auth = decrypt_auth(self._secret_box, p.api_key_ciphertext)
                except Exception:
                    logger.exception("厂商 %s 的上游凭证无法解密，跳过", p.slug)
                    continue
                providers[p.id] = (p.slug, p.base_url, auth)

            descriptors: dict[str, AiModelDescriptor] = {}
            for m in model_rows:
                prov = providers.get(m.provider_id)
                if prov is None:
                    continue  # 厂商被解密跳过，其下模型一并不可见
                slug, base_url, auth = prov
                descriptors[m.alias] = AiModelDescriptor(
                    model_id=m.id,
                    alias=m.alias,
                    provider_slug=slug,
                    provider_model_name=m.provider_model_name,
                    kind=m.kind or AI_MODEL_KIND_CHAT,
                    base_url=base_url,
                    auth=auth,
                    provider_id=m.provider_id,
                    input_price=_to_float(m.input_price),
                    output_price=_to_float(m.output_price),
                )

        snapshot = AiRegistrySnapshot(
            revision=revision, descriptors=MappingProxyType(descriptors)
        )
        self._snapshot = snapshot
        return snapshot


def _to_float(value) -> float | None:
    # Numeric(12,6) 读回来可能是 Decimal；转成 float 方便金额比较与序列化
    return float(value) if value is not None else None
