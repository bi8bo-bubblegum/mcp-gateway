from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.services.token_service import TokenSnapshot, value_matches_schema

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
        properties = (descriptor.input_schema or {}).get("properties") or {}
        for argument, value in injections.items():
            prop = properties.get(argument)
            if prop is None or not value_matches_schema(prop, value):
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
        """Return the effective arguments: injected values always win."""
        effective = dict(arguments or {})
        effective.update(snapshot.injections.get(descriptor.id, {}))
        return effective