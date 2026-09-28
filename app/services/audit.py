import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update

from app.core.security import TokenHasher
from app.db.base import utcnow
from app.db.models import AuditEvent, Token
from app.services.token_service import TokenSnapshot


class AuditWriteError(Exception):
    """Raised when the audit trail cannot be written.

    Callers must treat this as fatal for the request: the gateway does not make
    calls it cannot record.
    """


class AuditService:
    def __init__(self, *, hasher: TokenHasher, touch_interval: float = 60.0) -> None:
        self._hasher = hasher
        self._touch_interval = touch_interval
        self._touched_at: dict[int, float] = {}

    def _should_touch(self, token_id: int) -> bool:
        now = time.monotonic()
        last = self._touched_at.get(token_id)
        if last is not None and now - last < self._touch_interval:
            return False
        self._touched_at[token_id] = now
        return True

    def _hash_arguments(self, arguments: Mapping[str, Any] | None) -> dict[str, str]:
        return {
            key: self._hasher.fingerprint(value)
            for key, value in (arguments or {}).items()
        }

    async def start(
        self,
        *,
        request_id: str,
        token: TokenSnapshot | None,
        tool_name: str,
        service_slug: str | None,
        arguments: Mapping[str, Any] | None,
    ) -> int:
        """Persist the `started` record before the call executes.

        A failure here raises AuditWriteError so the caller can refuse the call.
        """
        from app.db.session import session_scope

        try:
            async with session_scope() as session:
                event = AuditEvent(
                    request_id=request_id,
                    token_id=token.id if token else None,
                    token_name=token.name if token else None,
                    service_slug=service_slug,
                    tool_name=tool_name,
                    status="started",
                    argument_keys=sorted((arguments or {}).keys()),
                    requested_argument_hashes=self._hash_arguments(arguments),
                    started_at=utcnow(),
                )
                session.add(event)
                if token is not None and self._should_touch(token.id):
                    await session.execute(
                        update(Token)
                        .where(Token.id == token.id)
                        .values(last_used_at=utcnow())
                    )
                await session.flush()
                return int(event.id)
        except Exception as error:  # noqa: BLE001 - surfaced as a hard failure
            raise AuditWriteError("could not persist audit start record") from error

    async def complete(
        self,
        event_id: int,
        *,
        status: str,
        denial_reason: str | None = None,
        error_type: str | None = None,
        effective_arguments: Mapping[str, Any] | None = None,
    ) -> None:
        """Finalize an audit record. Failures here are logged, never hidden."""
        from app.db.session import session_scope

        async with session_scope() as session:
            event = await session.get(AuditEvent, event_id)
            if event is None:
                return
            finished = utcnow()
            event.status = status
            event.denial_reason = denial_reason
            event.error_type = error_type
            event.finished_at = finished
            if effective_arguments is not None:
                event.effective_argument_hashes = self._hash_arguments(
                    effective_arguments
                )
            started = event.started_at
            if started is not None and started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
                if started is not None:
                    event.duration_ms = int((finished - started).total_seconds() * 1000)

    async def query(
        self,
        *,
        token_id: int | None = None,
        service_slug: str | None = None,
        tool_name: str | None = None,
        status: str | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, Sequence[AuditEvent]]:
        from app.db.session import session_scope

        conditions = []
        if token_id is not None:
            conditions.append(AuditEvent.token_id == token_id)
        if service_slug is not None:
            conditions.append(AuditEvent.service_slug == service_slug)
        if tool_name is not None:
            conditions.append(AuditEvent.tool_name == tool_name)
        if status is not None:
            conditions.append(AuditEvent.status == status)
        if started_after is not None:
            conditions.append(AuditEvent.started_at >= started_after)
        if started_before is not None:
            conditions.append(AuditEvent.started_at <= started_before)

        async with session_scope() as session:
            total_query = select(func.count(AuditEvent.id))
            rows_query = select(AuditEvent)
            for condition in conditions:
                total_query = total_query.where(condition)
                rows_query = rows_query.where(condition)
            total = int((await session.execute(total_query)).scalar_one())
            rows = await session.execute(
                rows_query.order_by(AuditEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
            items = list(rows.scalars())
        return total, items