"""护栏引擎：敏感词（首版纯关键词）匹配。

设计文档 §3.7 / §4.3。只做"规则引用"层面的命中判定：check 返回 GuardrailHit
列表（rule_id + rule_name），绝不带回命中原文——与审计"不留存命中原文"的哲学一致，
也避免把用户输入泄漏到日志或审计 JSON 里。

匹配语义：大小写不敏感子串；按规则 scope 过滤（request/response/both）；
both 在两侧都生效；仅启用的规则参与匹配。
"""
from dataclasses import dataclass
from typing import Sequence

from app.db.models import (
    GUARDRAIL_SCOPE_BOTH,
    GuardrailRule,
)


@dataclass(frozen=True)
class GuardrailHit:
    """一条命中：只携带规则引用，不携带任何用户输入原文。"""

    rule_id: int
    rule_name: str


class GuardrailEngine:
    def __init__(self, rules: Sequence[GuardrailRule]) -> None:
        # 构造时即筛掉未启用规则，check 热路径上不再判断 enabled
        self._rules = [r for r in rules if r.enabled]

    def check(self, text: str, phase: str) -> list[GuardrailHit]:
        """在指定阶段（request/response）扫描文本，返回命中的规则引用列表。"""
        hits: list[GuardrailHit] = []
        lowered = text.lower()
        for rule in self._rules:
            # scope 过滤：both 两侧生效，其余只在同名阶段生效
            if rule.scope == GUARDRAIL_SCOPE_BOTH:
                pass
            elif rule.scope != phase:
                continue
            # 大小写不敏感子串匹配；首版纯关键词，pattern.lower() 预存亦可
            if rule.pattern.lower() in lowered:
                hits.append(GuardrailHit(rule_id=rule.id, rule_name=rule.name))
        return hits
