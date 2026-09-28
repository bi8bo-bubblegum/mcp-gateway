import asyncio
import mcp_types

from dataclasses import dataclass, field
from typing import Any, Protocol
from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.tools import ToolResult

TOOL_NAME_SEPARATOR = "__"

def effective_tool_name(service_slug: str, upstream_name: str) -> str:
    return f"{service_slug}{TOOL_NAME_SEPARATOR}{upstream_name}"

def split_effective_name(name: str) -> tuple[str, str] | None:
    slug, separator, upstream = name.partition(TOOL_NAME_SEPARATOR)
    if not separator or not slug or not upstream:
        return None
    return slug, upstream

@dataclass(frozen=True)
class UpstreamAuth:
    bearer_token: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "UpstreamAuth":
        payload = payload or {}
        raw_headers = payload.get("headers") or {}
        headers = {str(k): str(v) for k, v in raw_headers.items()}
        bearer = payload.get("bearer_token")
        return cls(
            bearer_token=str(bearer) if bearer else None,
            headers=headers,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "bearer_token": self.bearer_token,
            "headers": dict(self.headers),
        }


@dataclass(frozen=True)
class UpstreamToolSpec:
    name: str
    description: str | None
    input_schema: dict[str, Any]

class UpstreamClientFactory(Protocol):
    def build(self, *, url: str, auth: UpstreamAuth, timeout: float) -> Client[Any]:
        ...

class StreamableHttpClientFactory:
    def build(self, *, url: str, auth: UpstreamAuth, timeout: float) -> Client[Any]:
        transport = StreamableHttpTransport(
            url=url,
            headers=dict(auth.headers),
            auth=auth.bearer_token
        )
        return Client(
            transport,
            name="gateway-upstream",
            timeout=timeout,
            init_timeout=timeout
        )

async def discover_tools(factory: UpstreamClientFactory, *, url: str, auth: UpstreamAuth, timeout: float) -> list[UpstreamToolSpec]:
    client = factory.build(url=url, auth=auth, timeout=timeout)
    async with asyncio.timeout(timeout):
        async with client:
            tools = await client.list_tools()
    return [
        UpstreamToolSpec(
            name=tool.name,
            description=tool.description,
            input_schema=dict(tool.input_schema or {}),
        )
        for tool in tools
    ]

async def call_upstream_tool(
        factory: UpstreamClientFactory,
        *,
        url: str,
        auth: UpstreamAuth,
        upstream_name: str,
        arguments: dict[str, Any],
        timeout: float,
) -> ToolResult:
    client = factory.build(url=url, auth=auth, timeout=timeout)
    async with asyncio.timeout(timeout):
        async with client:
            result = await client.call_tool_mcp(upstream_name, arguments)
    content = list(result.content or [])
    if not content and result.structured_content is None:
        content = [mcp_types.TextContent(type="text", text="")]
    return ToolResult(
        content=content,
        structured_content=result.structured_content,
        is_error=bool(result.is_error)
    )