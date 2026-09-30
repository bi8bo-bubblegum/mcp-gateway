"""AI 网关请求级审计服务（fail-closed）。

设计文档 §3.5 / §4.1⑦。每条 AI 请求写一条 ai_usage_events：start 在转发前落
status=started，失败则抛 AiAuditWriteError——调用方据此拒绝转发（fail-closed）。
complete 在响应后终结事件并记录用量/护栏命中/时延，并算 duration。

关键坑（与 MCP 审计同源）：utcnow() 返回 naive UTC，SQLite 取回的 started_at 也
是 naive，但某些路径下可能是 aware。两侧相减前必须显式补 tzinfo，否则
naive - aware 直接 TypeError，complete 失败、事件永远卡在 started。
"""
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.metering import Usage
from app.db.base import utcnow
from app.db.models import AiUsageEvent
from app.db.session import session_scope


class AiAuditWriteError(Exception):
    """审计主记录写不进去时抛出。

    调用方必须把它当请求级致命错误：网关不发出它无法记录的调用。
    """


class AiUsageService:
    async def start(
        self,
        *,
        request_id: str,
        endpoint: str,
        stream: bool,
        key_id: int | None = None,
        key_name: str | None = None,
        model_id: int | None = None,
        model_alias: str | None = None,
        provider_slug: str | None = None,
    ) -> int:
        """写 status=started 事件，返回事件 id。

        任何失败（DB 不可用、约束冲突等）都转成 AiAuditWriteError 抛出，
        让调用方在转发前就拒绝请求。
        """
        try:
            async with session_scope() as session:
                event = AiUsageEvent(
                    request_id=request_id,
                    key_id=key_id,
                    key_name=key_name,
                    model_id=model_id,
                    model_alias=model_alias,
                    provider_slug=provider_slug,
                    endpoint=endpoint,
                    stream=stream,
                    status="started",
                    started_at=utcnow(),
                )
                session.add(event)
                await session.flush()
                return int(event.id)
        except Exception as error:  # noqa: BLE001 - 统一转成 fail-closed 信号
            raise AiAuditWriteError("无法写入审计起始事件") from error

    async def complete(
        self,
        event_id: int,
        *,
        status: str,
        denial_reason: str | None = None,
        error_type: str | None = None,
        usage: Usage | None = None,
        guardrail_hits: Sequence[dict[str, Any]] | None = None,
        latency_ms: int | None = None,
        first_token_ms: int | None = None,
        upstream_status_code: int | None = None,
    ) -> None:
        """终结一条审计事件。失败只记日志，绝不影响已经发出的响应。"""
        async with session_scope() as session:
            event = await session.get(AiUsageEvent, event_id)
            if event is None:
                return
            event.status = status
            event.denial_reason = denial_reason
            event.error_type = error_type
            if usage is not None:
                event.prompt_tokens = usage.prompt_tokens
                event.completion_tokens = usage.completion_tokens
                event.total_tokens = usage.total_tokens
                event.usage_estimated = usage.estimated
            if guardrail_hits is not None:
                # 只存规则引用（rule_id/rule_name），不存命中原文
                event.guardrail_hits = [dict(h) for h in guardrail_hits]
            if first_token_ms is not None:
                event.first_token_ms = first_token_ms
            if upstream_status_code is not None:
                event.upstream_status_code = upstream_status_code
            if latency_ms is not None:
                # 调用方显式测得的时延优先
                event.latency_ms = latency_ms

            finished = utcnow()
            event.finished_at = finished
            started = event.started_at
            if started is not None:
                # 两侧都补 tzinfo 再相减：naive/aware 混算会 TypeError，
                # 那样 complete 失败、事件卡死在 started。
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if finished.tzinfo is None:
                    finished = finished.replace(tzinfo=timezone.utc)
                duration_ms = int((finished - started).total_seconds() * 1000)
                # 未显式提供时延时，用时间戳差值兜底（落点同上行回归）。
                if latency_ms is None:
                    event.latency_ms = duration_ms

    async def query(
        self,
        *,
        key_id: int | None = None,
        model_id: int | None = None,
        status: str | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, Sequence[AiUsageEvent]]:
        """过滤 + 分页查询审计事件，返回 (total, items)。"""
        conditions = []
        if key_id is not None:
            conditions.append(AiUsageEvent.key_id == key_id)
        if model_id is not None:
            conditions.append(AiUsageEvent.model_id == model_id)
        if status is not None:
            conditions.append(AiUsageEvent.status == status)
        if started_after is not None:
            conditions.append(AiUsageEvent.started_at >= started_after)
        if started_before is not None:
            conditions.append(AiUsageEvent.started_at <= started_before)

        async with session_scope() as session:
            total_query = select(func.count(AiUsageEvent.id))
            rows_query = select(AiUsageEvent)
            for condition in conditions:
                total_query = total_query.where(condition)
                rows_query = rows_query.where(condition)
            total = int((await session.execute(total_query)).scalar_one())
            rows = await session.execute(
                rows_query.order_by(AiUsageEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
            items = list(rows.scalars())
        return total, items
