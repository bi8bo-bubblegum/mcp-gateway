from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from sqlalchemy import select

from app.core.config import Settings
from app.core.security import SecretBox
from app.db.models import Service, Tool
from app.services.policy import ToolDescriptor
from app.services.revision import RevisionStore
from app.services.upstream import StreamableHttpClientFactory, UpstreamAuth, UpstreamClientFactory

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
        self._snapshot: RuntimeSnapshot | None = None

    @property
    def factory(self) -> UpstreamClientFactory:
        return self._factory

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
                services[row.id] = RuntimeService(
                    id=row.id,
                    slug=row.slug,
                    name=row.slug,
                    url=row.url,
                    auth=self._decrypt_auth(row.auth_ciphertext),
                )

            descriptors: dict[str, ToolDescriptor] = {}
            for row in tool_rows:
                descriptors[row.effective_name] = ToolDescriptor(
                    id=row.id,
                    service_id=row.service_id,
                    service_slug=services[row.service_id].slug,
                    upstream_name=row.upstream_name,
                    effective_name=row.effective_name,
                    description=row.description,
                    risk=row.risk,
                    enabled=row.enabled,
                    available=row.available,
                    input_schema=dict(row.input_schema or {}),
                )

        self._snapshot = RuntimeSnapshot(
            revision=revision,
            services=MappingProxyType(services),
            descriptors=MappingProxyType(descriptors),
        )
        return self._snapshot

    def _decrypt_auth(self, ciphertext: str | None) -> UpstreamAuth:
        if not ciphertext:
            return  UpstreamAuth()
        return UpstreamAuth.from_payload(self._secret_box.decrypt(ciphertext))


