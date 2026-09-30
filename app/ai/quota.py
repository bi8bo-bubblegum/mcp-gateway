"""配额判定与进程内限流。

设计文档 §4.1④⑤ / §3.6。配额热路径读 ai_usage_daily：day 读当日行、month 求和
当月行；等于限额即拒（不是超过才拒）。period=none 或限额为 null 一律放行。
限流是进程内滑动窗口（单进程速率近似），rpm 为 None 直接放行。

时间约定：本模块所有"今天"都用 utcnow().date() 取 naive UTC 日期，与上游
记账写入 ai_usage_daily 的 day 同源，避免本地时区与 UTC 错位导致跨日口径不一致。
（naive/aware 混用会在时间差计算时直接 TypeError，故两侧都保持 naive。）
"""
import time
from collections import deque
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.base import utcnow
from app.db.models import (
    AI_KEY_PERIOD_DAY,
    AI_KEY_PERIOD_MONTH,
    AI_KEY_PERIOD_NONE,
    AiUsageDaily,
)
from app.services.ai_key_service import AiKeySnapshot


class QuotaChecker:
    async def check(self, session: AsyncSession, snapshot: AiKeySnapshot) -> bool:
        """返回 True 表示放行，False 表示超出配额（应 429 insufficient_quota）。

        period=none 或 period_token_limit 为 null → 不限配额，直接放行。
        """
        if snapshot.period == AI_KEY_PERIOD_NONE or snapshot.period_token_limit is None:
            return True

        today = utcnow().date()
        if snapshot.period == AI_KEY_PERIOD_DAY:
            rec = (
                await session.execute(
                    select(AiUsageDaily).where(
                        AiUsageDaily.key_id == snapshot.id,
                        AiUsageDaily.day == today,
                    )
                )
            ).scalar_one_or_none()
            used = rec.total_tokens if rec is not None else 0
        elif snapshot.period == AI_KEY_PERIOD_MONTH:
            first = today.replace(day=1)
            used = int(
                (
                    await session.execute(
                        select(
                            func.coalesce(func.sum(AiUsageDaily.total_tokens), 0)
                        ).where(
                            AiUsageDaily.key_id == snapshot.id,
                            AiUsageDaily.day >= first,
                            AiUsageDaily.day <= today,
                        )
                    )
                ).scalar_one()
            )
        else:
            # 未知 period 兜底放行，不阻断正常请求
            return True

        # 等于限额即拒
        return used < snapshot.period_token_limit


class RateLimiter:
    """进程内滑动窗口限流（单实例速率近似）。

    窗口长 settings.ai_rate_limit_window；rpm 为 None 表示不限速，直接放行。
    按 key_id 各自维护一个时间戳 deque，allow 时先清掉窗口外的旧记录再判满。
    """

    def __init__(self, settings: Settings) -> None:
        self._window = settings.ai_rate_limit_window
        self._hits: dict[int, deque[float]] = {}

    def allow(self, key_id: int, rpm: int | None) -> bool:
        if rpm is None:
            return True
        now = time.monotonic()
        dq = self._hits.setdefault(key_id, deque())
        cutoff = now - self._window
        # 清掉滑出窗口的旧请求，否则窗口永不腾出空间
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= rpm:
            return False
        dq.append(now)
        return True
