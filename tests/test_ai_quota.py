"""QuotaChecker / RateLimiter 测试。

配额：period=none 或限额 null 一律放行；day 读当日汇总；month 求和当月；
等于限额即拒（不是超过才拒）。限流：进程内滑动窗口，rpm=None 直接放行，
窗口满即拒，旧请求滑出窗口后重新放行。
"""
import time
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.ai.quota import QuotaChecker, RateLimiter
from app.core.config import Settings
from app.db.base import utcnow
from app.db.models import (
    AI_KEY_PERIOD_DAY,
    AI_KEY_PERIOD_MONTH,
    AI_KEY_PERIOD_NONE,
    AiUsageDaily,
)
from app.services.ai_key_service import AiKeySnapshot


def _snap(key_id=1, *, period=AI_KEY_PERIOD_NONE, limit=None, rpm=None) -> AiKeySnapshot:
    return AiKeySnapshot(
        id=key_id,
        name="k",
        allowed_model_ids=frozenset(),
        period=period,
        period_token_limit=limit,
        rate_limit_rpm=rpm,
    )


# ── 配额 ──────────────────────────────────────────────────────────

async def test_under_limit_passes(db, settings):
    checker = QuotaChecker()
    snap = _snap(period=AI_KEY_PERIOD_DAY, limit=100)
    async with db() as session:
        today = utcnow().date()
        session.add(AiUsageDaily(
            key_id=1, day=today, requests=1,
            prompt_tokens=0, completion_tokens=0, total_tokens=50,
        ))
        await session.commit()
        assert await checker.check(session, snap) is True


async def test_exact_limit_blocks(db, settings):
    checker = QuotaChecker()
    snap = _snap(period=AI_KEY_PERIOD_DAY, limit=100)
    async with db() as session:
        today = utcnow().date()
        session.add(AiUsageDaily(
            key_id=1, day=today, requests=1,
            prompt_tokens=0, completion_tokens=0, total_tokens=100,
        ))
        await session.commit()
        # 等于限额即拒，不是超过才拒
        assert await checker.check(session, snap) is False


async def test_null_limit_never_blocks(db, settings):
    checker = QuotaChecker()
    snap = _snap(period=AI_KEY_PERIOD_DAY, limit=None)
    async with db() as session:
        today = utcnow().date()
        session.add(AiUsageDaily(key_id=1, day=today, total_tokens=999999))
        await session.commit()
        assert await checker.check(session, snap) is True
    # period=none 也放行（即使限额写 0）
    snap2 = _snap(period=AI_KEY_PERIOD_NONE, limit=0)
    async with db() as session:
        assert await checker.check(session, snap2) is True


async def test_month_period_sums_days(db, settings):
    checker = QuotaChecker()
    today = utcnow().date()
    first = today.replace(day=1)
    # 保证两个不同日期（避免当月首日时复合主键冲突），且都在 [first, today] 内
    second = today + timedelta(days=1) if first == today else today
    async with db() as session:
        session.add(AiUsageDaily(key_id=1, day=first, total_tokens=300))
        session.add(AiUsageDaily(key_id=1, day=second, total_tokens=200))
        await session.commit()
        # 当月累计 500 < 1000 → 放行
        assert await checker.check(session, _snap(period=AI_KEY_PERIOD_MONTH, limit=1000)) is True
    # 累计 500 == 限额 → 拒
    async with db() as session:
        assert await checker.check(session, _snap(period=AI_KEY_PERIOD_MONTH, limit=500)) is False


# ── 限流 ──────────────────────────────────────────────────────────

async def test_rate_limit_window_blocks_after_rpm(settings):
    limiter = RateLimiter(settings)
    rpm = 2
    assert limiter.allow(1, rpm) is True
    assert limiter.allow(1, rpm) is True
    assert limiter.allow(1, rpm) is False  # 已达上限


async def test_rate_limit_window_slides(settings):
    limiter = RateLimiter(settings)
    rpm = 1
    assert limiter.allow(1, rpm) is True
    assert limiter.allow(1, rpm) is False  # 窗口满
    # 把窗口内唯一的一次请求时间戳推到窗口之外，模拟它已滑出
    dq = limiter._hits[1]
    dq[0] = time.monotonic() - (limiter._window + 1)
    assert limiter.allow(1, rpm) is True  # 旧请求滑出后重新放行


async def test_rate_limit_none_rpm_always_allows(settings):
    limiter = RateLimiter(settings)
    for _ in range(5):
        assert limiter.allow(1, None) is True
