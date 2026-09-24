import time

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GatewayRevision
from app.db.session import session_scope

REVISION_ROW_ID = 1

async def ensure_revision_row(session: AsyncSession) -> None:
    existing = await session.get(GatewayRevision, REVISION_ROW_ID)
    if existing is not None:
        return
    session.add(GatewayRevision(id=REVISION_ROW_ID, revision=0))
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()

async def bump_revision(session: AsyncSession) -> int:
    await ensure_revision_row(session)
    await session.execute(
        update(GatewayRevision)
        .where(GatewayRevision.id == REVISION_ROW_ID)
        .values(revision=GatewayRevision.revision + 1)
    )
    result = await session.execute(
        select(GatewayRevision.revision).where(
            GatewayRevision.id == REVISION_ROW_ID
        )
    )
    return int(result.scalar_one())

class RevisionStore:
    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._revision: int | None = None
        self._checked_at: float = 0.0

    def invalidate(self) -> None:
        """Force the next read to hit the database (used after a local admin write)."""
        self._checked_at = 0.0

    async def current(self) -> int:
        now = time.monotonic()
        if self._revision is not None and now - self._checked_at < self._ttl:
            return self._revision
        async with session_scope() as session:
            result = await session.execute(
                select(GatewayRevision.revision).where(
                    GatewayRevision.id == REVISION_ROW_ID
                )
            )
            value = result.scalar_one_or_none()
        self._revision = int(value or 0)
        self._checked_at = now
        return self._revision