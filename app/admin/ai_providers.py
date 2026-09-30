"""厂商管理接口（/admin/v1/ai/providers）。"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_container, require_admin
from app.db.session import get_session
from app.schemas.ai import (
    AiProviderCreate,
    AiProviderRead,
    AiProviderUpdate,
)
from app.services.ai_provider_service import AiProviderServiceError

router = APIRouter(
    prefix="/admin/v1/ai/providers",
    tags=["ai-providers"],
    dependencies=[Depends(require_admin)],
)


def _service(request: Request):
    return get_container(request).ai_providers


@router.get("", response_model=list[AiProviderRead])
async def list_providers(
    request: Request, session: AsyncSession = Depends(get_session)
):
    rows = await _service(request).list(session)
    return [AiProviderRead.model_validate(row) for row in rows]


@router.post("", response_model=AiProviderRead, status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: AiProviderCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        provider = await _service(request).create(session, payload)
    except AiProviderServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return AiProviderRead.model_validate(provider)


@router.get("/{provider_id}", response_model=AiProviderRead)
async def get_provider(
    provider_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        provider = await _service(request).get(session, provider_id)
    except AiProviderServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AiProviderRead.model_validate(provider)


@router.patch("/{provider_id}", response_model=AiProviderRead)
async def update_provider(
    provider_id: int,
    payload: AiProviderUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        provider = await _service(request).update(session, provider_id, payload)
    except AiProviderServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return AiProviderRead.model_validate(provider)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        await _service(request).delete(session, provider_id)
    except AiProviderServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/{provider_id}/enable", response_model=AiProviderRead)
async def enable_provider(
    provider_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        provider = await _service(request).set_enabled(session, provider_id, True)
    except AiProviderServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AiProviderRead.model_validate(provider)


@router.post("/{provider_id}/disable", response_model=AiProviderRead)
async def disable_provider(
    provider_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        provider = await _service(request).set_enabled(session, provider_id, False)
    except AiProviderServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AiProviderRead.model_validate(provider)


@router.post("/{provider_id}/health", response_model=AiProviderRead)
async def check_provider_health(
    provider_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        provider = await _service(request).check_health(session, provider_id)
    except AiProviderServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AiProviderRead.model_validate(provider)
