"""护栏规则服务（管理端）：CRUD + 批量粘贴导入。

不 bump_revision：GuardrailLoader 每个请求都按 enabled 重查一次 DB，没有缓存
需要失效；反过来说，管理端改完规则**下一个请求即生效**（有 e2e 测试锁定）。
"""
# 本类有名为 list 的方法，会让类体内的 list[...] 注解解析成方法对象，故延迟求值
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GuardrailRule
from app.schemas.ai import (
    GuardrailBulkCreate,
    GuardrailRuleCreate,
    GuardrailRuleUpdate,
)


class AiGuardrailServiceError(Exception):
    """规则不存在。"""


class AiGuardrailService:
    async def list(self, session: AsyncSession) -> list[GuardrailRule]:
        rows = await session.execute(select(GuardrailRule).order_by(GuardrailRule.id))
        return list(rows.scalars())

    async def get(self, session: AsyncSession, rule_id: int) -> GuardrailRule:
        row = await session.get(GuardrailRule, rule_id)
        if row is None:
            raise AiGuardrailServiceError(f"护栏规则 {rule_id} 不存在")
        return row

    async def create(
        self, session: AsyncSession, payload: GuardrailRuleCreate
    ) -> GuardrailRule:
        rule = GuardrailRule(
            name=payload.name,
            pattern=payload.pattern,
            scope=payload.scope,
            action=payload.action,
            enabled=payload.enabled,
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        return rule

    async def update(
        self, session: AsyncSession, rule_id: int, payload: GuardrailRuleUpdate
    ) -> GuardrailRule:
        rule = await self.get(session, rule_id)
        if payload.name is not None:
            rule.name = payload.name
        if payload.pattern is not None:
            rule.pattern = payload.pattern
        if payload.scope is not None:
            rule.scope = payload.scope
        if payload.action is not None:
            rule.action = payload.action
        if payload.enabled is not None:
            rule.enabled = payload.enabled
        await session.commit()
        await session.refresh(rule)
        return rule

    async def delete(self, session: AsyncSession, rule_id: int) -> None:
        rule = await self.get(session, rule_id)
        await session.delete(rule)
        await session.commit()

    async def bulk_create(
        self, session: AsyncSession, payload: GuardrailBulkCreate
    ) -> tuple[int, int, list[GuardrailRule]]:
        """按行拆关键词导入，返回 (created, skipped, 新建的行)。

        跳过两类：空行，以及关键词已存在（大小写不敏感——引擎匹配本身就不区分
        大小写，若按区分大小写去重会导进两条永远同时命中的重复规则）。
        规则名取关键词本身（可加 name_prefix 便于分组识别）。
        """
        existing = {
            str(p).lower()
            for p in (await session.execute(select(GuardrailRule.pattern))).scalars()
        }
        seen: set[str] = set()
        created: list[GuardrailRule] = []
        skipped = 0
        for raw_line in payload.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if lowered in existing or lowered in seen:
                skipped += 1
                continue
            seen.add(lowered)
            name = f"{payload.name_prefix}{line}"[:128]
            rule = GuardrailRule(
                name=name,
                pattern=line,
                scope=payload.scope,
                action=payload.action,
                enabled=payload.enabled,
            )
            session.add(rule)
            created.append(rule)

        if created:
            await session.commit()
            for rule in created:
                await session.refresh(rule)
        return len(created), skipped, created
