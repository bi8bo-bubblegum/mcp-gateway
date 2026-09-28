import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import SecretBox, TokenHasher
from app.db.base import utcnow
from app.db.models import Service, Tool
from app.schemas.service import ServiceCreate, ServiceUpdate
from app.services.revision import bump_revision
from app.services.upstream import (
    UpstreamAuth,
    UpstreamClientFactory,
    discover_tools,
    effective_tool_name,
)

MAX_ERROR_LENGTH = 2000


class ServiceManagerError(Exception):
    """Raised for admin-facing service management failures."""



@dataclass(frozen=True)
class RefreshResult:
    service_id: int
    discovered: int
    created: int
    updated: int
    removed: int


class ServiceManager:
    def __init__(
        self,
        *,
        settings: Settings,
        factory: UpstreamClientFactory,
        secret_box: SecretBox,
        hasher: TokenHasher,
    ) -> None:
        self._settings = settings
        self._factory = factory
        self._secret_box = secret_box
        self._hasher = hasher

    # ---------------------------------------------------------------- reads

    async def list_services(self, session: AsyncSession) -> Sequence[Service]:
        result = await session.execute(select(Service).order_by(Service.slug))
        return list(result.scalars())

    async def get_service(self, session: AsyncSession, service_id: int) -> Service:
        service = await session.get(Service, service_id)
        if service is None:
            raise ServiceManagerError(f"service {service_id} not found")
        return service

    # --------------------------------------------------------------- writes

    async def create_service(
        self, session: AsyncSession, payload: ServiceCreate
    ) -> Service:
        existing = await session.execute(
            select(Service.id).where(Service.slug == payload.slug)
        )
        if existing.scalar_one_or_none() is not None:
            raise ServiceManagerError(f"slug '{payload.slug}' already exists")

        service = Service(
            slug=payload.slug,
            name=payload.name,
            url=payload.url,
            auth_ciphertext=self._encrypt_auth(payload.auth),
            enabled=False,
            health="unknown",
        )
        session.add(service)
        await session.flush()
        service_id = service.id
        await bump_revision(session)
        await session.commit()

        # Discovery runs outside the transaction: a slow upstream must not hold
        # a database transaction open.
        await self.refresh_tools(service_id)
        # refresh_tools 走的是独立 session，本 session 内存里仍是发现之前的旧值，
        # 必须先过期，否则下面读到的 health 永远停留在 "unknown"。
        session.expire_all()
        if payload.enabled:
            # Auto-enable is only honored once discovery actually succeeded.
            fresh = await self.get_service(session, service_id)
            if fresh.health == "healthy":
                await self.set_enabled(session, service_id, True)

        session.expire_all()
        return await self.get_service(session, service_id)

    async def update_service(
        self, session: AsyncSession, service_id: int, payload: ServiceUpdate
    ) -> Service:
        service = await self.get_service(session, service_id)
        reconnect_required = False

        if payload.name is not None:
            service.name = payload.name
        if payload.url is not None and payload.url != service.url:
            service.url = payload.url
            reconnect_required = True
        if payload.auth is not None:
            service.auth_ciphertext = self._encrypt_auth(payload.auth)
            reconnect_required = True

        await bump_revision(session)
        await session.commit()

        if reconnect_required:
            await self.refresh_tools(service_id)
            # 同上：丢弃本 session 的陈旧状态，否则 set_enabled 会拿到旧 health。
            session.expire_all()

        if payload.enabled is not None:
            await self.set_enabled(session, service_id, payload.enabled)

        session.expire_all()
        return await self.get_service(session, service_id)

    async def set_enabled(
        self, session: AsyncSession, service_id: int, enabled: bool
    ) -> Service:
        service = await self.get_service(session, service_id)
        if enabled and service.health != "healthy":
            raise ServiceManagerError(
                f"service '{service.slug}' is not healthy; refresh credentials first"
            )
        service.enabled = enabled
        await bump_revision(session)
        await session.commit()
        await session.refresh(service)
        return service

    async def delete_service(self, session: AsyncSession, service_id: int) -> None:
        service = await self.get_service(session, service_id)
        await session.delete(service)
        await bump_revision(session)
        await session.commit()

    # ---------------------------------------------------------- discovery

    async def refresh_tools(self, service_id: int) -> RefreshResult:
        """Discover the upstream catalog and reconcile it with the database.

        Discovery happens before the write transaction so a slow or dead upstream
        cannot hold database locks.
        """
        from app.db.session import session_scope

        async with session_scope() as session:
            service = await self.get_service(session, service_id)
            slug, url = service.slug, service.url
            auth = self._decrypt_auth(service.auth_ciphertext)

        try:
            specs = await discover_tools(
                self._factory,
                url=url,
                auth=auth,
                timeout=self._settings.discovery_timeout,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - reported to admin, not swallowed
            await self._record_refresh_failure(service_id, error)
            return RefreshResult(service_id, 0, 0, 0, 0)

        async with session_scope() as session:
            service = await self.get_service(session, service_id)
            existing = {
                tool.upstream_name: tool
                for tool in (
                    await session.execute(
                        select(Tool).where(Tool.service_id == service_id)
                    )
                ).scalars()
            }
            seen: set[str] = set()
            created = updated = 0

            for spec in specs:
                seen.add(spec.name)
                schema_hash = self._hasher.fingerprint(spec.input_schema)
                row = existing.get(spec.name)
                if row is None:
                    session.add(
                        Tool(
                            service_id=service_id,
                            upstream_name=spec.name,
                            effective_name=effective_tool_name(slug, spec.name),
                            description=spec.description,
                            input_schema=spec.input_schema,
                            schema_hash=schema_hash,
                            # Default high: an admin must confirm before use.
                            risk="high",
                            enabled=True,
                            available=True,
                        )
                    )
                    created += 1
                else:
                    row.description = spec.description
                    row.input_schema = spec.input_schema
                    row.schema_hash = schema_hash
                    row.available = True
                    updated += 1

            removed = 0
            for name, row in existing.items():
                if name not in seen and row.available:
                    # Keep the row for audit history; only mark it unusable.
                    row.available = False
                    removed += 1

            service.health = "healthy"
            service.consecutive_failures = 0
            service.last_error = None
            service.last_refreshed_at = utcnow()
            service.last_checked_at = utcnow()
            await bump_revision(session)

        return RefreshResult(
            service_id=service_id,
            discovered=len(specs),
            created=created,
            updated=updated,
            removed=removed,
        )

    async def check_health(self, service_id: int) -> bool:
        from app.db.session import session_scope

        async with session_scope() as session:
            service = await self.get_service(session, service_id)
            url = service.url
            auth = self._decrypt_auth(service.auth_ciphertext)

        error: str | None = None
        try:
            client = self._factory.build(
                url=url, auth=auth, timeout=self._settings.health_timeout
            )
            async with asyncio.timeout(self._settings.health_timeout):
                async with client:
                    await client.ping()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - health failures are data
            error = f"{type(exc).__name__}: {exc}"

        recovered = False
        async with session_scope() as session:
            service = await self.get_service(session, service_id)
            service.last_checked_at = utcnow()
            if error is None:
                recovered = service.health != "healthy"
                service.health = "healthy"
                service.consecutive_failures = 0
                service.last_error = None
            else:
                service.consecutive_failures += 1
                service.last_error = error[:MAX_ERROR_LENGTH]
                if (
                    service.consecutive_failures
                    >= self._settings.health_failure_threshold
                ):
                    service.health = "unhealthy"
            await bump_revision(session)

        if recovered:
            # A recovered server may have changed its catalog while it was down.
            await self.refresh_tools(service_id)

        return error is None

    async def list_enabled_service_ids(self, session: AsyncSession) -> list[int]:
        result = await session.execute(
            select(Service.id).where(Service.enabled.is_(True))
        )
        return [int(row) for row in result.scalars()]

    # -------------------------------------------------------------- helpers

    async def _record_refresh_failure(self, service_id: int, error: Exception) -> None:
        from app.db.session import session_scope

        async with session_scope() as session:
            service = await self.get_service(session, service_id)
            service.health = "unhealthy"
            service.consecutive_failures += 1
            service.last_error = f"{type(error).__name__}: {error}"[:MAX_ERROR_LENGTH]
            service.last_checked_at = utcnow()
            await bump_revision(session)

    def _encrypt_auth(self, auth: object | None) -> str | None:
        if auth is None:
            return None
        payload = auth.model_dump()  # type: ignore[attr-defined]
        headers = payload.get("headers") or {}
        bearer = payload.get("bearer_token")
        if not bearer and not headers:
            return None
        return self._secret_box.encrypt(UpstreamAuth(
            bearer_token=bearer, headers=headers
        ).to_payload())

    def _decrypt_auth(self, ciphertext: str | None) -> UpstreamAuth:
        if not ciphertext:
            return UpstreamAuth()
        return UpstreamAuth.from_payload(self._secret_box.decrypt(ciphertext))

    @staticmethod
    def now() -> datetime:
        return utcnow()