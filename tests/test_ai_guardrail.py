"""GuardrailEngine 测试：按 phase 与 scope 过滤、大小写不敏感子串匹配、
只返回规则引用（绝不带回命中原文）。

护栏规则直接以内存对象传入（与审计"不留存命中原文"的哲学一致），路由层负责
把库里的规则加载进来再构造引擎；本测试只验证匹配语义。
"""
import pytest

from app.ai.guardrail import GuardrailEngine, GuardrailHit
from app.db.models import (
    GUARDRAIL_ACTION_BLOCK,
    GUARDRAIL_SCOPE_BOTH,
    GUARDRAIL_SCOPE_REQUEST,
    GUARDRAIL_SCOPE_RESPONSE,
    GuardrailRule,
)


def _rule(rule_id, pattern, scope, *, name=None, enabled=True):
    return GuardrailRule(
        id=rule_id,
        name=name or f"rule{rule_id}",
        pattern=pattern,
        scope=scope,
        action=GUARDRAIL_ACTION_BLOCK,
        enabled=enabled,
    )


async def test_request_hit_is_blocked():
    engine = GuardrailEngine(rules=[_rule(1, "secret", GUARDRAIL_SCOPE_REQUEST)])
    hits = engine.check("this contains secret info", "request")
    assert len(hits) == 1
    assert isinstance(hits[0], GuardrailHit)
    assert hits[0].rule_id == 1


async def test_response_scope_not_checked_on_request():
    # 仅 response 作用域的规则，在 request 阶段不应命中
    engine = GuardrailEngine(rules=[_rule(1, "secret", GUARDRAIL_SCOPE_RESPONSE)])
    assert engine.check("this contains secret info", "request") == []


async def test_case_insensitive_substring():
    engine = GuardrailEngine(rules=[_rule(1, "secret", GUARDRAIL_SCOPE_REQUEST)])
    hits = engine.check("leaked SECRET key", "request")
    assert len(hits) == 1
    assert hits[0].rule_id == 1


async def test_both_scope_hits_on_both_phases():
    engine = GuardrailEngine(rules=[_rule(1, "x", GUARDRAIL_SCOPE_BOTH)])
    assert len(engine.check("contains x", "request")) == 1
    assert len(engine.check("contains x", "response")) == 1


async def test_disabled_rule_ignored():
    engine = GuardrailEngine(
        rules=[_rule(1, "x", GUARDRAIL_SCOPE_REQUEST, enabled=False)]
    )
    assert engine.check("has x here", "request") == []


async def test_hits_return_rule_refs_not_text():
    engine = GuardrailEngine(
        rules=[_rule(7, "password", GUARDRAIL_SCOPE_BOTH, name="pwd-rule")]
    )
    hits = engine.check("my password is 123", "response")
    assert len(hits) == 1
    hit = hits[0]
    # 只返回规则引用（id + 名称），绝不含命中原文
    assert hit.rule_id == 7
    assert hit.rule_name == "pwd-rule"
    assert not hasattr(hit, "matched_text")
