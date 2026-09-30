"""AI Key 管理接口（/admin/v1/ai/keys）。

明文只在创建响应（AiKeyCreated）里出现一次；其余接口一律走 AiKeyRead，不含
key/key_hash 字段——这是与 MCP 令牌一致的纪律，前端也据此只弹一次明文框。
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_container, require_admin
from app.db.models import AiApiKey, AiKeyModel
from app.db.session import get_session
from app.schemas.ai import (
    AiKeyCreate,
    AiKeyCreated,
    AiKeyDetail,
    AiKeyPolicyUpdate,
    AiKeyRead,
)
from app.services.ai_key_service import AiKeyServiceError

router = APIRouter(
    prefix="/admin/v1/ai/keys",
    tags=["ai-keys"],
    dependencies=[Depends(require_admin)],
)


def _service(request: Request):
    return get_container(request).ai_keys


async def _model_ids(session: AsyncSession, key_id: int) -> list[int]:
    rows = await session.execute(
        select(AiKeyModel.model_id).where(AiKeyModel.key_id == key_id)
    )
    return sorted(int(m) for m in rows.scalars())


@router.get("", response_model=list[AiKeyRead])
async def list_keys(request: Request, session: AsyncSession = Depends(get_session)):
    rows = await session.execute(select(AiApiKey).order_by(AiApiKey.id))
    return [AiKeyRead.model_validate(row) for row in rows.scalars()]


@router.post("", response_model=AiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: AiKeyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    key, raw = await _service(request).create(session, payload)
    detail = AiKeyDetail.model_validate(key).model_copy(
        update={"model_ids": sorted(set(payload.model_ids))}
    )
    return AiKeyCreated(**detail.model_dump(), key=raw)


@router.get("/{key_id}", response_model=AiKeyDetail)
async def get_key(
    key_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    key = await session.get(AiApiKey, key_id)
    if key is None:
        raise HTTPException(status_code=404, detail=f"AI Key {key_id} 不存在")
    detail = AiKeyDetail.model_validate(key).model_copy(
        update={"model_ids": await _model_ids(session, key_id)}
    )
    return detail


@router.patch("/{key_id}", response_model=AiKeyRead)
async def update_key(
    key_id: int,
    payload: AiKeyPolicyUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        key = await _service(request).update_policy(session, key_id, payload)
    except AiKeyServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AiKeyRead.model_validate(key)


@router.post("/{key_id}/revoke", response_model=AiKeyRead)
async def revoke_key(
    key_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        key = await _service(request).revoke(session, key_id)
    except AiKeyServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AiKeyRead.model_validate(key)
