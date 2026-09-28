from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_container, require_admin
from app.db.models import Token
from app.db.session import get_session
from app.schemas.token import (
    ParameterInjectionRead,
    TokenCreate,
    TokenCreated,
    TokenPolicyUpdate,
    TokenRead,
)
from app.services.token_service import TokenServiceError

router = APIRouter(
    prefix="/admin/v1/tokens",
    tags=["tokens"],
    dependencies=[Depends(require_admin)],
)


async def _to_read(service, session: AsyncSession, token: Token) -> TokenRead:
    visible, allowed, injections = await service.policy_detail(session, token.id)
    return TokenRead(
        id=token.id,
        name=token.name,
        token_prefix=token.token_prefix,
        enabled=token.enabled,
        allow_high_risk=token.allow_high_risk,
        created_at=token.created_at,
        revoked_at=token.revoked_at,
        last_used_at=token.last_used_at,
        visible_service_ids=visible,
        allowed_tool_ids=allowed,
        parameter_injections=[
            ParameterInjectionRead.model_validate(row) for row in injections
        ],
    )


@router.post("", response_model=TokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    payload: TokenCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    service = get_container(request).token_service
    try:
        token, raw = await service.create(session, payload)
    except TokenServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    detail = await _to_read(service, session, token)
    return TokenCreated(**detail.model_dump(), token=raw)


@router.get("", response_model=list[TokenRead])
async def list_tokens(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    service = get_container(request).token_service
    rows = await service.list_tokens(session)
    return [await _to_read(service, session, row) for row in rows]


@router.get("/{token_id}", response_model=TokenRead)
async def get_token(
    token_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    service = get_container(request).token_service
    try:
        token = await service.get(session, token_id)
    except TokenServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return await _to_read(service, session, token)


@router.patch("/{token_id}", response_model=TokenRead)
async def update_token(
    token_id: int,
    payload: TokenPolicyUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    service = get_container(request).token_service
    try:
        token = await service.update_policy(session, token_id, payload)
    except TokenServiceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return await _to_read(service, session, token)


@router.post("/{token_id}/revoke", response_model=TokenRead)
async def revoke_token(
    token_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    service = get_container(request).token_service
    try:
        token = await service.revoke(session, token_id)
    except TokenServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return await _to_read(service, session, token)