"""模型管理接口（/admin/v1/ai/models）。

注意路由顺序：`/pull` 必须声明在 `/{model_id}` 之前，否则 "pull" 会先被当作
model_id 解析，直接 422。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_container, require_admin
from app.db.session import get_session
from app.schemas.ai import (
    AiModelCreate,
    AiModelImportRequest,
    AiModelRead,
    AiModelUpdate,
    AiPullModelRead,
)
from app.services.ai_model_service import AiModelServiceError
from app.services.ai_provider_service import AiProviderServiceError

router = APIRouter(
    prefix="/admin/v1/ai/models",
    tags=["ai-models"],
    dependencies=[Depends(require_admin)],
)


def _models(request: Request):
    return get_container(request).ai_models


def _providers(request: Request):
    return get_container(request).ai_providers


@router.get("", response_model=list[AiModelRead])
async def list_models(
    request: Request,
    provider_id: int | None = Query(default=None),
    kind: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    rows = await _models(request).list(session, provider_id=provider_id, kind=kind)
    return [AiModelRead.model_validate(row) for row in rows]


@router.post("", response_model=AiModelRead, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: AiModelCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        model = await _models(request).create(session, payload)
    except AiModelServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return AiModelRead.model_validate(model)


@router.get("/pull", response_model=list[AiPullModelRead])
async def pull_models(
    request: Request,
    provider_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
):
    """代理上游 GET /v1/models，返回候选清单供勾选导入。"""
    try:
        items = await _providers(request).pull_models(session, provider_id)
    except AiProviderServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return [AiPullModelRead.model_validate(item) for item in items]


@router.post("/import")
async def import_models(
    payload: AiModelImportRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        created, skipped, rows = await _models(request).import_models(session, payload)
    except AiModelServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "created": created,
        "skipped": skipped,
        "models": [AiModelRead.model_validate(row) for row in rows],
    }


@router.get("/{model_id}", response_model=AiModelRead)
async def get_model(
    model_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        model = await _models(request).get(session, model_id)
    except AiModelServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AiModelRead.model_validate(model)


@router.patch("/{model_id}", response_model=AiModelRead)
async def update_model(
    model_id: int,
    payload: AiModelUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        model = await _models(request).update(session, model_id, payload)
    except AiModelServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return AiModelRead.model_validate(model)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        await _models(request).delete(session, model_id)
    except AiModelServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
