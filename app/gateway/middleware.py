import asyncio
import logging
from collections.abc import Sequence
from email import message
from ftplib import error_temp
from uuid import uuid4

import mcp_types
import mcp_types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext, CallNext
from fastmcp.tools import Tool, ToolResult

from app.gateway.auth import current_token_claims
from app.gateway.runtime import RuntimeRegistry
from app.services.audit import AuditService, AuditWriteError
from app.services.policy import PolicyService
from app.services.token_service import TokenService
from app.services.upstream import split_effective_name

logger = logging.getLogger(__name__)

STATE_EFFECTIVE_ARGUMENTS = "gateway.effective_arguments"
STATE_DENIAL_REASON = "gateway.denial_reason"
REASON_TOOL_NOT_FOUND = "tool_not_found"

class PolicyMiddleware(Middleware):

    def __init__(self, *, tokens: TokenService, registry: RuntimeRegistry) -> None:
        self._tokens = tokens
        self._registry = registry

    async def _snapshot(self):
        token_id, _ = current_token_claims()
        if token_id is None:
            return None
        return await self._tokens.snapshot_by_id(token_id)

    async def on_list_tools(self, context: MiddlewareContext[mcp_types.ListToolsRequest], call_next) -> Sequence[Tool]:
        tools = await call_next(context)
        snapshot = await self._snapshot()
        if snapshot is None:
            return []
        runtime = await self._registry.snapshot()
        visible = {
            descriptor.effective_name for descriptor in PolicyService.visible_tools(snapshot, runtime.all_descriptors())
        }
        return [tool for tool in tools if tool.name in visible]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        snapshot = await self._snapshot()
        runtime = await self._registry.snapshot()
        descriptor = runtime.descriptor(name)
        if snapshot is None or descriptor is None:
            await self._note_denial(context, REASON_TOOL_NOT_FOUND)
            raise ToolError(f"Unknown tool: {name}")

        decision = PolicyService.decide(snapshot, descriptor)
        if not decision.allowed:
            await self._note_denial(context, decision.reason or "denied")
            raise ToolError(f"Unknown tool: {name}")

        effective = PolicyService.apply_injections(
            snapshot, descriptor, context.message.arguments
        )
        if context.fastmcp_context is not None:
            await context.fastmcp_context.set_state(
                STATE_EFFECTIVE_ARGUMENTS, effective, serializable=False
            )

        forwarded = context.message.model_copy(update={"arguments": effective})
        return await call_next(context.copy(message=forwarded))

    async def _note_denial(self, context: MiddlewareContext, reason: str) -> None:
        if context.fastmcp_context is not None:
            await context.fastmcp_context.set_state(STATE_DENIAL_REASON, reason, serializable=False)

class AuditMiddleware(Middleware):
    def __init__(self, *, tokens: TokenService, audit: AuditService) -> None:
        self._tokens = tokens
        self._audit = audit

    @staticmethod
    def _request_id(context: MiddlewareContext) -> str:
        ctx = context.fastmcp_context
        if ctx is not None and ctx.request_context is not None:
            try:
                return str(ctx.request_id)
            except Exception:
                pass
        return uuid4().hex

    async def on_call_tool(self, context: MiddlewareContext[mcp_types.CallToolRequestParams], call_next) -> ToolResult:
        name = context.message.name or ""
        token_id, _ = current_token_claims()
        snapshot = (
            await self._tokens.snapshot_by_id(token_id)
            if token_id is not None else None
        )
        parsed = split_effective_name(name)
        service_slug = parsed[0] if parsed else None

        try:
            event_id = await self._audit.start(
                request_id=self._request_id(context),
                token=snapshot,
                tool_name=name,
                service_slug=service_slug,
                arguments=context.message.arguments
            )
        except AuditWriteError as error:
            raise ToolError("Audit unavailable; call refused") from error

        try:
            result = await call_next(context)
        except asyncio.CancelledError:
            await self._finish(context, event_id, "failed", error_type="CancelledError")
            raise
        except ToolError:
            await self._finish(context, event_id, "denied")
            raise
        except Exception as error:
            await self._finish(context, event_id, "failed", error_type=type(error).__name__)
            raise

        await self._finish(context, event_id, "succeeded")
        return result

    async def _finish(self, context: MiddlewareContext, event_id: int, status: str, *, error_type: str | None = None) -> None:
        reason = None
        effective = None
        ctx = context.fastmcp_context
        if ctx is not None:
            reason = await ctx.get_state(STATE_DENIAL_REASON)
            effective = await ctx.get_state(STATE_EFFECTIVE_ARGUMENTS)
        try:
            await asyncio.shield(
                self._audit.complete(
                    event_id,
                    status=status,
                    denial_reason=reason,
                    error_type=error_type,
                    effective_arguments=effective
                )
            )
        except BaseException:
            logger.exception("could not finalize audit event %s", event_id)
