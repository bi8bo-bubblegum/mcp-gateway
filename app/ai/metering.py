"""计量：上游 usage 解析、字符估算、日汇总累加 upsert。

设计文档 §3.5/§3.6/§4.2。本模块只负责"把用量变成可记账的数字"与"把数字累进
日汇总表"，不关心请求链路。

时间约定：所有"今天"统一用 utcnow().date() 取 naive UTC 日期，与配额热路径
（app/ai/quota.py）及后续审计同源，避免本地时区与 UTC 错位导致跨日口径不一致。
"""
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models import AiUsageDaily

# 字符估算比例：英文约 4 字符/token，中文约 1.5~2 字符/token，取 4 作为保守上界，
# 仅用于流式降级时"有个数"而非精确计数——精确与否由 estimated 标记诚实说明。
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class Usage:
    """一次请求的 token 用量。estimated=True 表示来自字符估算而非上游精确返回。"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated: bool = False


def parse_usage(payload: Any) -> Usage | None:
    """解析上游响应里的 usage。

    兼容两种入参：整段响应（含 "usage" 键）或直接传入 usage 片段。三字段
    （prompt_tokens/completion_tokens/total_tokens）必须齐全且为 int，否则返回
    None——诚实原则：字段不全就不假装能精确记账，调用方应降级到估算。
    """
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage", payload)
    if not isinstance(usage, dict):
        return None
    try:
        prompt = usage["prompt_tokens"]
        completion = usage["completion_tokens"]
        total = usage["total_tokens"]
    except (KeyError, TypeError):
        return None
    if not isinstance(prompt, int) or not isinstance(completion, int) or not isinstance(total, int):
        return None
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        estimated=False,
    )


def estimate_usage(text: str) -> Usage:
    """按字符数估算 token（流式降级路径）。

    流式响应侧我们只看得到已吐出的内容，prompt 端未知，故 prompt_tokens 记 0，
    completion/total 取估算值，并显式标 estimated=True，绝不假装精确。
    """
    tokens = (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN
    return Usage(
        prompt_tokens=0,
        completion_tokens=tokens,
        total_tokens=tokens,
        estimated=True,
    )


async def record_daily(session: AsyncSession, key_id: int, usage: Usage) -> None:
    """把一次用量累加进 ai_usage_daily 的 (key_id, day) 行。

    用"先 SELECT 再 UPDATE/INSERT"的通用写法，避免 MySQL 专有的
    ON DUPLICATE KEY UPDATE（测试跑 SQLite，且要双库兼容）。并发下的极小竞态
    是已知取舍（见计划风险表），首版不引行锁/Redis。
    """
    day = utcnow().date()
    rec = (
        await session.execute(
            select(AiUsageDaily).where(
                AiUsageDaily.key_id == key_id, AiUsageDaily.day == day
            )
        )
    ).scalar_one_or_none()

    if rec is None:
        # 新的一天/新的 key：先落一条全 0 基线再累加，保证后续 UPDATE 有目标行
        rec = AiUsageDaily(
            key_id=key_id,
            day=day,
            requests=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
        )
        session.add(rec)
        await session.flush()

    rec.requests += 1
    rec.prompt_tokens += usage.prompt_tokens
    rec.completion_tokens += usage.completion_tokens
    rec.total_tokens += usage.total_tokens
    await session.flush()
