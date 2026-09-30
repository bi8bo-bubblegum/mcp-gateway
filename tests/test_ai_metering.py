"""计量模块测试：usage 解析、字符估算、日汇总累加。

设计文档 §3.5/§3.6/§4.2。parse_usage 对上游 usage 严格取三字段（缺则 None），
estimate_usage 走字符估算并标 estimated=True，record_daily 用"先查再写"实现
通用 upsert（SQLite/MySQL 双兼容），"今天"统一用 utcnow().date()。
"""
from sqlalchemy import select

from app.ai.metering import Usage, estimate_usage, parse_usage, record_daily
from app.db.models import AiUsageDaily
from app.db.base import utcnow


# ── parse_usage ──────────────────────────────────────────────────

def test_parse_usage_from_json():
    # 上游 chat 返回的 usage 三字段齐全 → 解析成功，estimated=False
    u = parse_usage(
        {"usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}}
    )
    assert u is not None
    assert (u.prompt_tokens, u.completion_tokens, u.total_tokens) == (5, 7, 12)
    assert u.estimated is False


def test_parse_usage_accepts_bare_usage_dict():
    # 也接受直接传入 usage 片段（非整段响应）
    u = parse_usage({"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
    assert u is not None and u.total_tokens == 3


def test_parse_usage_missing_returns_none():
    # 字段不全 / 类型错 / 整体缺失 → 一律 None（诚实：不假装精确）
    assert parse_usage(None) is None
    assert parse_usage({"usage": {"prompt_tokens": 5}}) is None  # 缺 completion/total
    assert parse_usage({"usage": {"prompt_tokens": "x", "completion_tokens": 7, "total_tokens": 12}}) is None


# ── estimate_usage ───────────────────────────────────────────────

def test_estimate_marks_estimated():
    text = "这是一段用于估算 token 的示例文本，长度会影响结果"
    u = estimate_usage(text)
    assert u.estimated is True
    # 字符估算：约 1 token / 4 字符，非空文本应得到正 token 数
    assert u.total_tokens > 0
    # 估算只知内容侧长度，prompt 未知记作 0，total 与 completion 一致
    assert u.prompt_tokens == 0
    assert u.completion_tokens == u.total_tokens


# ── record_daily ─────────────────────────────────────────────────

async def test_upsert_daily_accumulates(db, settings):
    # 同一 (key_id, 今天) 两次记账应累加而非覆盖
    async with db() as session:
        await record_daily(session, 1, Usage(5, 7, 12, False))
        await record_daily(session, 1, Usage(3, 4, 7, True))
        await session.commit()

    async with db() as session:
        rec = (
            await session.execute(
                select(AiUsageDaily).where(AiUsageDaily.key_id == 1)
            )
        ).scalar_one()
        assert rec.day == utcnow().date()
        assert rec.requests == 2
        assert rec.prompt_tokens == 8
        assert rec.completion_tokens == 11
        assert rec.total_tokens == 19


async def test_record_daily_isolated_per_day_and_key(db, settings):
    # 不同 key 互不影响
    async with db() as session:
        await record_daily(session, 1, Usage(1, 1, 2, False))
        await record_daily(session, 2, Usage(10, 10, 20, False))
        await session.commit()

    async with db() as session:
        rows = (
            await session.execute(select(AiUsageDaily).order_by(AiUsageDaily.key_id))
        ).scalars().all()
        assert [(r.key_id, r.total_tokens) for r in rows] == [(1, 2), (2, 20)]
