"""审计服务测试：start(fail-closed) / complete(含 naive-aware 回归) / query。

设计文档 §3.5 / §4.1⑦。start 写 status=started，失败抛 AiAuditWriteError（fail-closed
依据）；complete 终结事件并算 duration——两侧时间都补 tzinfo，否则 naive-naive/aware
混算会 TypeError 把事件永远卡在 started（MCP 网关踩过的坑）；query 支持过滤 + 分页。
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.ai.metering import Usage
from app.db.models import AiUsageEvent
from app.services.ai_usage_service import AiAuditWriteError, AiUsageService


# ── start（fail-closed） ──────────────────────────────────────────

async def test_start_writes_started_event(db, settings):
    svc = AiUsageService()
    eid = await svc.start(
        request_id="r1",
        key_id=1,
        key_name="key-a",
        model_id=2,
        model_alias="gpt-mini",
        provider_slug="openai",
        endpoint="chat.completions",
        stream=False,
    )
    assert isinstance(eid, int)
    async with db() as session:
        row = await session.get(AiUsageEvent, eid)
        assert row is not None
        assert row.status == "started"
        assert row.key_id == 1
        assert row.model_alias == "gpt-mini"
        assert row.provider_slug == "openai"


async def test_start_raises_audit_write_error_on_failure(db, settings, monkeypatch):
    # fail-closed：底层写不进去必须抛 AiAuditWriteError，让调用方拒绝转发
    @asynccontextmanager
    async def _boom():
        raise RuntimeError("数据库挂了")
        yield  # pragma: no cover

    import app.db.session as s
    from app.services import ai_usage_service

    monkeypatch.setattr(ai_usage_service, "session_scope", _boom)
    svc = AiUsageService()
    with pytest.raises(AiAuditWriteError):
        await svc.start(request_id="x", endpoint="chat.completions", stream=False)


# ── complete（终结态 + duration 回归） ────────────────────────────

async def test_complete_writes_terminal_state(db, settings):
    svc = AiUsageService()
    async with db() as session:
        ev = AiUsageEvent(
            request_id="r", endpoint="chat.completions", stream=False, status="started"
        )
        session.add(ev)
        await session.commit()
        eid = int(ev.id)

    await svc.complete(
        eid,
        status="succeeded",
        usage=Usage(5, 7, 12, False),
        latency_ms=123,
        upstream_status_code=200,
    )

    async with db() as session:
        row = await session.get(AiUsageEvent, eid)
        assert row.status == "succeeded"
        assert row.prompt_tokens == 5
        assert row.completion_tokens == 7
        assert row.total_tokens == 12
        assert row.usage_estimated is False
        assert row.latency_ms == 123
        assert row.upstream_status_code == 200
        assert isinstance(row.latency_ms, int)  # 已正常终态化，没被 TypeError 卡死


async def test_complete_records_denial_and_guardrail_hits(db, settings):
    svc = AiUsageService()
    async with db() as session:
        ev = AiUsageEvent(
            request_id="r", endpoint="chat.completions", stream=False, status="started"
        )
        session.add(ev)
        await session.commit()
        eid = int(ev.id)

    await svc.complete(
        eid,
        status="denied",
        denial_reason="guardrail_blocked",
        error_type="guardrail_blocked",
        guardrail_hits=[{"rule_id": 1, "rule_name": "敏感词A"}],
    )

    async with db() as session:
        row = await session.get(AiUsageEvent, eid)
        assert row.status == "denied"
        assert row.denial_reason == "guardrail_blocked"
        # 只存规则引用，不存命中原文
        assert row.guardrail_hits == [{"rule_id": 1, "rule_name": "敏感词A"}]


async def test_complete_accepts_naive_and_aware_timestamps(db, settings):
    # 回归锁：started_at 带时区而 finished_at 为 naive（或反之）时，相减不能 TypeError。
    svc = AiUsageService()
    async with db() as session:
        ev = AiUsageEvent(
            request_id="r",
            endpoint="chat.completions",
            stream=False,
            status="started",
            # 故意造一条带时区的 started_at，复现"一侧 aware 一侧 naive"
            started_at=datetime.now(timezone.utc),
        )
        session.add(ev)
        await session.commit()
        eid = int(ev.id)

    # complete 内部 finished_at = utcnow() 是 naive，与上面的 aware started_at 混算
    await svc.complete(eid, status="succeeded")

    async with db() as session:
        row = await session.get(AiUsageEvent, eid)
        assert row.status == "succeeded"
        assert isinstance(row.latency_ms, int)  # 没有 TypeError


# ── query（过滤 + 分页） ──────────────────────────────────────────

async def test_query_filters_and_pages(db, settings):
    svc = AiUsageService()
    async with db() as session:
        for i in range(5):
            session.add(
                AiUsageEvent(
                    request_id=f"r{i}",
                    endpoint="chat.completions",
                    stream=False,
                    status="succeeded" if i % 2 == 0 else "failed",
                    key_id=1,
                )
            )
        await session.commit()

    # 状态过滤
    total_ok, items_ok = await svc.query(status="succeeded")
    assert total_ok == 3
    assert all(r.status == "succeeded" for r in items_ok)

    # 全量计数 + 分页
    total_all, items_all = await svc.query(limit=2, offset=0)
    assert total_all == 5
    assert len(items_all) == 2

    # 第二页不越界
    _, items_p2 = await svc.query(limit=2, offset=4)
    assert len(items_p2) == 1

    # key_id 过滤
    total_key, _ = await svc.query(key_id=1)
    assert total_key == 5
