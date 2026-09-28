from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_container, require_admin
from app.db.session import get_session
from app.schemas.service import (
    ServiceCreate,
    ServiceRead,
    ServiceRefreshResult,
    ServiceUpdate,
)
from app.services.service_manager import ServiceManagerError

router = APIRouter(
    prefix="/admin/v1/services",
    tags=["services"],
    dependencies=[Depends(require_admin)],
)


def _manager(request: Request):
    return get_container(request).service_manager


@router.get("", response_model=list[ServiceRead])
async def list_services(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    rows = await _manager(request).list_services(session)
    return [ServiceRead.model_validate(row) for row in rows]


@router.post(
    "", response_model=ServiceRead, status_code=status.HTTP_201_CREATED
)
async def create_service(
    payload: ServiceCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        service = await _manager(request).create_service(session, payload)
    except ServiceManagerError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ServiceRead.model_validate(service)


@router.get("/{service_id}", response_model=ServiceRead)
async def get_service(
    service_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        service = await _manager(request).get_service(session, service_id)
    except ServiceManagerError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return ServiceRead.model_validate(service)


@router.patch("/{service_id}", response_model=ServiceRead)
async def update_service(
    service_id: int,
    payload: ServiceUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        service = await _manager(request).update_service(session, service_id, payload)
    except ServiceManagerError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ServiceRead.model_validate(service)


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    service_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        await _manager(request).delete_service(session, service_id)
    except ServiceManagerError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/{service_id}/enable", response_model=ServiceRead)
async def enable_service(
    service_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        service = await _manager(request).set_enabled(session, service_id, True)
    except ServiceManagerError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ServiceRead.model_validate(service)


@router.post("/{service_id}/disable", response_model=ServiceRead)
async def disable_service(
    service_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        service = await _manager(request).set_enabled(session, service_id, False)
    except ServiceManagerError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ServiceRead.model_validate(service)


@router.post("/{service_id}/refresh", response_model=ServiceRefreshResult)
async def refresh_service(request: Request, service_id: int):
    try:
        result = await _manager(request).refresh_tools(service_id)
    except ServiceManagerError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return ServiceRefreshResult(
        service_id=result.service_id,
        discovered=result.discovered,
        created=result.created,
        updated=result.updated,
        removed=result.removed,
    )


@router.post("/{service_id}/health", response_model=ServiceRead)
async def check_service_health(
    service_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    manager = _manager(request)
    try:
        await manager.check_health(service_id)
        service = await manager.get_service(session, service_id)
    except ServiceManagerError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return ServiceRead.model_validate(service)