import asyncio
import logging

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from sqlalchemy import select

from app.core.config import Settings
from app.core.security import SecretBox
from app.db.models import Service, Tool
from app.services.policy import ToolDescriptor
from app.services.revision import RevisionStore
from app.services.upstream import (
    StreamableHttpClientFactory,
    UpstreamAuth,
    UpstreamClientFactory,
    UpstreamClientPool,
    decrypt_auth,
)

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class RuntimeService:
    id: int
    slug: str
    name: str
    url: str
    auth: UpstreamAuth

@dataclass(frozen=True)
class RuntimeSnapshot:
    revision: int
    services: Mapping[int, RuntimeService]
    descriptors: Mapping[str, ToolDescriptor]

    def descriptor(self, effective_name: str) -> ToolDescriptor | None:
        return self.descriptors.get(effective_name)

    def all_descriptors(self) -> list[ToolDescriptor]:
        return list(self.descriptors.values())

class RuntimeRegistry:
    def __init__(self, *, settings: Settings, revisions: RevisionStore, secret_box: SecretBox, factory: UpstreamClientFactory | None = None) -> None:
        self._settings = settings
        self._revisions = revisions
        self._secret_box = secret_box
        self._factory = factory or StreamableHttpClientFactory()
        self._pool = UpstreamClientPool(
            self._factory,
            size=settings.upstream_pool_size,
            max_slot_idle=settings.upstream_pool_slot_max_idle,
        )
        self._snapshot: RuntimeSnapshot | None = None
        self._lock = asyncio.Lock()

    @property
    def pool(self) -> UpstreamClientPool:
        """工具调用复用长连接的入口。"""
        return self._pool

    @property
    def upstream_timeout(self) -> float:
        return self._settings.upstream_timeout

    def invalidate(self) -> None:
        self._snapshot = None

    async def snapshot(self) -> RuntimeSnapshot:
        revision = await self._revisions.current()
        cached = self._snapshot
        if cached is not None and cached.revision == revision:
            return cached
        # revision 变化后所有请求都会同时到达这里，没有锁就是 N 份重复的
        # 全表查询。锁内重新读一次 revision 并复查，避免排队者重复重建。
        async with self._lock:
            revision = await self._revisions.current()
            cached = self._snapshot
            if cached is not None and cached.revision == revision:
                return cached
            return await self._rebuild(revision)

    async def _rebuild(self, revision: int) -> RuntimeSnapshot:
        from app.db.session import session_scope
        async with session_scope() as session:
            service_rows = list(
                (
                    await session.execute(
                        select(Service)
                        .where(Service.enabled.is_(True), Service.health == "healthy")
                        .order_by(Service.slug)
                    )
                ).scalars()
            )
            service_ids = [row.id for row in service_rows]
            tool_rows: list[Tool] = []
            if service_ids:
                tool_rows = list(
                    (
                        await session.execute(
                            select(Tool)
                            .where(
                                Tool.service_id.in_(service_ids),
                                Tool.enabled.is_(True),
                                Tool.available.is_(True),
                            )
                            .order_by(Tool.effective_name)
                        )
                    ).scalars()
                )

            services: dict[int, RuntimeService] = {}
            for row in service_rows:
                try:
                    auth = decrypt_auth(self._secret_box, row.auth_ciphertext)
                except Exception:
                    logger.exception("service %s 的上游凭证无法解密，跳过该服务", row.slug)
                    continue
                services[row.id] = RuntimeService(
                    id=row.id,
                    slug=row.slug,
                    name=row.slug,
                    url=row.url,
                    auth=auth,
                )

            descriptors: dict[str, ToolDescriptor] = {}
            for row in tool_rows:
                service = services.get(row.service_id)
                if service is None:
                    continue
                descriptors[row.effective_name] = ToolDescriptor(
                    id=row.id,
                    service_id=row.service_id,
                    service_slug=service.slug,
                    upstream_name=row.upstream_name,
                    effective_name=row.effective_name,
                    description=row.description,
                    risk=row.risk,
                    enabled=row.enabled,
                    available=row.available,
                    input_schema=dict(row.input_schema or {}),
                )

        snapshot = RuntimeSnapshot(
            revision=revision,
            services=MappingProxyType(services),
            descriptors=MappingProxyType(descriptors),
        )
        self._snapshot = snapshot
        return snapshot


