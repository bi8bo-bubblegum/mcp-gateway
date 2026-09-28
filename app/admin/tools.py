from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_container, require_admin
from app.db.models import Service, Tool
from app.db.session import get_session
from app.schemas.tool import ToolRead, ToolUpdate
from app.services.revision import bump_revision

router = APIRouter(
    prefix="/admin/v1/tools",
    tags=["tools"],
    dependencies=[Depends(require_admin)],
)


def _to_read(tool: Tool, service_slug: str) -> ToolRead:
    return ToolRead(
        id=tool.id,
        service_id=tool.service_id,
        service_slug=service_slug,
        upstream_name=tool.upstream_name,
        effective_name=tool.effective_name,
        description=tool.description,
        input_schema=dict(tool.input_schema or {}),
        schema_hash=tool.schema_hash,
        risk=tool.risk,
        enabled=tool.enabled,
        available=tool.available,
        discovered_at=tool.discovered_at,
        updated_at=tool.updated_at,
    )


@router.get("", response_model=list[ToolRead])
async def list_tools(
    service_id: int | None = None,
    session: AsyncSession = Depends(get_session),
):
    query = select(Tool, Service.slug).join(Service, Tool.service_id == Service.id)
    if service_id is not None:
        query = query.where(Tool.service_id == service_id)
    rows = await session.execute(query.order_by(Tool.effective_name))
    return [_to_read(tool, slug) for tool, slug in rows.all()]


@router.get("/{tool_id}", response_model=ToolRead)
async def get_tool(tool_id: int, session: AsyncSession = Depends(get_session)):
    row = (
        await session.execute(
            select(Tool, Service.slug)
            .join(Service, Tool.service_id == Service.id)
            .where(Tool.id == tool_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id} not found")
    tool, slug = row
    return _to_read(tool, slug)


@router.patch("/{tool_id}", response_model=ToolRead)
async def update_tool(
    tool_id: int,
    payload: ToolUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    tool = await session.get(Tool, tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id} not found")
    if payload.risk is not None:
        tool.risk = payload.risk
    if payload.enabled is not None:
        tool.enabled = payload.enabled

    await bump_revision(session)
    await session.commit()

    container = get_container(request)
    container.revisions.invalidate()
    container.registry.invalidate()

    row = (
        await session.execute(
            select(Tool, Service.slug)
            .join(Service, Tool.service_id == Service.id)
            .where(Tool.id == tool_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"tool {tool_id} not found")
    updated, slug = row
    return _to_read(updated, slug)