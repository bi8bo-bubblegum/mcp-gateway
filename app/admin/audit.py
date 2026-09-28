from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request

from app.admin.deps import get_container, require_admin
from app.schemas.audit import AuditEventPage, AuditEventRead

router = APIRouter(
    prefix="/admin/v1/audit-events",
    tags=["audit"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=AuditEventPage)
async def list_audit_events(
    request: Request,
    token_id: int | None = None,
    service_slug: str | None = None,
    tool_name: str | None = None,
    status: str | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    audit = get_container(request).audit_service
    total, rows = await audit.query(
        token_id=token_id,
        service_slug=service_slug,
        tool_name=tool_name,
        status=status,
        started_after=started_after,
        started_before=started_before,
        limit=limit,
        offset=offset,
    )
    return AuditEventPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[AuditEventRead.model_validate(row) for row in rows],
    )