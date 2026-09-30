"""用量审计接口（/admin/v1/ai/usage）。"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request

from app.admin.deps import get_container, require_admin
from app.schemas.ai import AiUsageDailyRead, AiUsageEventPage, AiUsageEventRead

router = APIRouter(
    prefix="/admin/v1/ai/usage",
    tags=["ai-usage"],
    dependencies=[Depends(require_admin)],
)


def _service(request: Request):
    return get_container(request).ai_usage


@router.get("/events", response_model=AiUsageEventPage)
async def list_events(
    request: Request,
    key_id: int | None = Query(default=None),
    model_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    started_after: datetime | None = Query(default=None),
    started_before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    total, rows = await _service(request).query(
        key_id=key_id,
        model_id=model_id,
        status=status,
        started_after=started_after,
        started_before=started_before,
        limit=limit,
        offset=offset,
    )
    return AiUsageEventPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[AiUsageEventRead.model_validate(row) for row in rows],
    )


@router.get("/daily", response_model=list[AiUsageDailyRead])
async def list_daily(
    request: Request,
    key_id: int | None = Query(default=None),
    day_from: date | None = Query(default=None, alias="from"),
    day_to: date | None = Query(default=None, alias="to"),
):
    rows = await _service(request).query_daily(
        key_id=key_id, day_from=day_from, day_to=day_to
    )
    return [AiUsageDailyRead.model_validate(row) for row in rows]
