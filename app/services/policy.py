from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.services.token_service import (
    TokenSnapshot,
    resolve_injection_target,
    value_matches_schema,
)

DENY_SERVICE_NOT_VISIBLE = "service_not_visible"
DENY_TOOL_NOT_ALLOWED = "tool_not_allowed"
DENY_HIGH_RISK_NOT_ALLOWED = "high_risk_not_allowed"
DENY_TOOL_UNAVAILABLE = "tool_unavailable"
DENY_INJECTION_INVALID = "injection_invalid"


@dataclass(frozen=True)
class ToolDescriptor:
    """Database state for one tool, snapshotted for the current revision."""

    id: int
    service_id: int
    service_slug: str
    upstream_name: str
    effective_name: str
    description: str | None
    risk: str
    enabled: bool
    available: bool
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None


class PolicyService:
    """Three-level authorization: server, tool, high-risk, then parameter injection.

    Every check is deny-by-default. A tool that is disabled, unavailable, on an
    invisible service, absent from the allow list, or high risk without the
    explicit flag cannot be listed or called.
    """

    @staticmethod
    def visible_tools(
        snapshot: TokenSnapshot, descriptors: Iterable[ToolDescriptor]
    ) -> list[ToolDescriptor]:
        return [
            descriptor
            for descriptor in descriptors
            if PolicyService.decide(snapshot, descriptor).allowed
        ]

    @staticmethod
    def decide(
        snapshot: TokenSnapshot,
        descriptor: ToolDescriptor,
    ) -> PolicyDecision:
        if not descriptor.enabled or not descriptor.available:
            return PolicyDecision(False, DENY_TOOL_UNAVAILABLE)
        if descriptor.service_id not in snapshot.visible_service_ids:
            return PolicyDecision(False, DENY_SERVICE_NOT_VISIBLE)
        if descriptor.id not in snapshot.allowed_tool_ids:
            return PolicyDecision(False, DENY_TOOL_NOT_ALLOWED)
        if descriptor.risk == "high" and not snapshot.allow_high_risk:
            return PolicyDecision(False, DENY_HIGH_RISK_NOT_ALLOWED)
        injections = snapshot.injections.get(descriptor.id, {})
        for argument, value in injections.items():
            target = resolve_injection_target(descriptor.input_schema, argument)
            if target is None or not value_matches_schema(target[1], value):
                # A stored rule that no longer matches the upstream schema is a
                # configuration fault. Fail closed; never forward unmanaged.
                return PolicyDecision(False, DENY_INJECTION_INVALID)
        return PolicyDecision(True)

    @staticmethod
    def apply_injections(
        snapshot: TokenSnapshot,
        descriptor: ToolDescriptor,
        arguments: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Return the effective arguments: injected values always win.

        注入键解析成参数路径后深合并：`request.phones` 只替换 request 里的
        phones，调用方传的 orderNos、pageSize 等兄弟参数原样保留。
        """
        effective = dict(arguments or {})
        injections = snapshot.injections.get(descriptor.id, {})
        for argument in sorted(injections):
            target = resolve_injection_target(descriptor.input_schema, argument)
            # decide() 用同一个解析函数放行过，这里理论上不会失配；真失配时
            # 退回顶层同名键——宁可多覆盖一个参数，也不静默丢掉这条约束。
            path = target[0] if target is not None else (argument,)
            _assign_path(effective, path, injections[argument])
        return effective


def _assign_path(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """把 value 写到 target 的嵌套路径上。

    逐层复制经过的对象，绝不改动调用方传进来的 arguments 内部结构；
    中间层已存在但不是对象时，整体换成对象（注入值始终优先）。
    """
    node = target
    for part in path[:-1]:
        existing = node.get(part)
        node[part] = dict(existing) if isinstance(existing, dict) else {}
        node = node[part]
    node[path[-1]] = value