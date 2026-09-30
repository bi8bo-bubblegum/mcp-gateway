"""护栏规则管理接口（/admin/v1/ai/guardrails）。"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import get_container, require_admin
from app.db.session import get_session
from app.schemas.ai import (
    GuardrailBulkCreate,
    GuardrailBulkResult,
    GuardrailRuleCreate,
    GuardrailRuleRead,
    GuardrailRuleUpdate,
)
from app.services.ai_guardrail_service import AiGuardrailServiceError

router = APIRouter(
    prefix="/admin/v1/ai/guardrails",
    tags=["ai-guardrails"],
    dependencies=[Depends(require_admin)],
)


def _service(request: Request):
    # 注意：container.ai_guardrails 是数据面的 GuardrailLoader，管理端写入服务是
    # ai_guardrail_service，两者不是一回事
    return get_container(request).ai_guardrail_service


@router.get("", response_model=list[GuardrailRuleRead])
async def list_rules(request: Request, session: AsyncSession = Depends(get_session)):
    rows = await _service(request).list(session)
    return [GuardrailRuleRead.model_validate(row) for row in rows]


@router.post("", response_model=GuardrailRuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: GuardrailRuleCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    rule = await _service(request).create(session, payload)
    return GuardrailRuleRead.model_validate(rule)


@router.post("/bulk", response_model=GuardrailBulkResult)
async def bulk_create_rules(
    payload: GuardrailBulkCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    created, skipped, rows = await _service(request).bulk_create(session, payload)
    return GuardrailBulkResult(
        created=created,
        skipped=skipped,
        rules=[GuardrailRuleRead.model_validate(row) for row in rows],
    )


@router.patch("/{rule_id}", response_model=GuardrailRuleRead)
async def update_rule(
    rule_id: int,
    payload: GuardrailRuleUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        rule = await _service(request).update(session, rule_id, payload)
    except AiGuardrailServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return GuardrailRuleRead.model_validate(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    try:
        await _service(request).delete(session, rule_id)
    except AiGuardrailServiceError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
